import os
from datetime import datetime, timezone

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from tweety import Twitter

from configs.load_configs import configs
from core.classes import Cog_Extension
from src.discord_ui.modal import CustomizeMsgModal
from src.log import setup_logger
from src.notification.account_tracker import AccountTracker
from src.permission import ADMINISTRATOR
from src.utils import get_accounts

log = setup_logger(__name__)

load_dotenv()


class Notification(Cog_Extension):
    def __init__(self, bot):
        super().__init__(bot)
        self.account_tracker = AccountTracker(bot)

    add_group = app_commands.Group(name='add', description='Add something', default_permissions=ADMINISTRATOR)
    remove_group = app_commands.Group(name='remove', description='Remove something', default_permissions=ADMINISTRATOR)
    customize_group = app_commands.Group(name='customize', description='Customize something', default_permissions=ADMINISTRATOR)

    @add_group.command(name='notifier')
    @app_commands.choices(
        enable_type=[app_commands.Choice(name='All (default)', value='11'), app_commands.Choice(name='Tweet & Retweet Only', value='10'), app_commands.Choice(name='Tweet & Quote Only', value='01'), app_commands.Choice(name='Tweet Only', value='00')],
        media_type=[app_commands.Choice(name='All (default)', value='11'), app_commands.Choice(name='No Media', value='10'), app_commands.Choice(name='Media Only', value='01')],
        account_used=[app_commands.Choice(name=account_name, value=account_name) for account_name, _ in get_accounts().items()]
    )
    @app_commands.rename(enable_type='type')
    async def notifier(self, itn: discord.Interaction, username: str, channel: discord.TextChannel, account_used: str, mention: discord.Role = None, enable_type: str = '11', media_type: str = '11'):
        """Add a twitter user to specific channel on your server.

        Parameters
        -----------
        username: str
            The username of the twitter user you want to turn on notifications for.
        channel: discord.TextChannel
            The channel to which the bot delivers notifications.
        account_used: str
            The account used to deliver notifications.
        mention: discord.Role
            The role to mention when notifying.
        type: str
            Whether to enable notifications for retweets & quotes.
        media_type: str
            Whether to enable notifications for All Tweets, Tweets with Media, or Tweets without Media Only.
        """

        await itn.response.defer(ephemeral=True)

        async with aiosqlite.connect(os.path.join(os.getenv('DATA_PATH'), 'tracked_accounts.db')) as db:
            db.row_factory = aiosqlite.Row
            async with db.cursor() as cursor:

                await cursor.execute('SELECT * FROM user WHERE username = ?', (username,))
                match_user = await cursor.fetchone()

                server_id = str(channel.guild.id)
                roleID = str(mention.id) if mention is not None else ''
                if match_user is None or match_user['enabled'] == 0:
                    app = Twitter(account_used)
                    app.load_auth_token(get_accounts()[account_used])
                    try:
                        new_user = app.get_user_info(username)
                    except Exception:
                        await itn.followup.send(f'user {username} not found', ephemeral=True)
                        return

                    if match_user is None:
                        await cursor.execute('INSERT INTO user (id, username, lastest_tweet, client_used) VALUES (?, ?, ?, ?)', (str(new_user.id), username, datetime.utcnow().replace(tzinfo=timezone.utc).strftime('%Y-%m-%d %H:%M:%S%z'), account_used))
                        await cursor.execute('INSERT OR IGNORE INTO channel VALUES (?, ?)', (str(channel.id), server_id))
                        await cursor.execute('INSERT INTO notification (user_id, channel_id, role_id, enable_type, enable_media_type) VALUES (?, ?, ?, ?, ?)', (str(new_user.id), str(channel.id), roleID, enable_type, media_type))
                    else:
                        if match_user['client_used'] != account_used and configs['auto_change_client']:
                            if configs['auto_unfollow'] or configs['auto_turn_off_notification']:
                                old_client_used = match_user['client_used']
                                old_app = Twitter(old_client_used)
                                old_app.load_auth_token(get_accounts()[old_client_used])
                                target_user = old_app.get_user_info(username)

                                if configs['auto_unfollow']:
                                    log.info(f'successfully unfollowed {username} (due to client change)') if old_app.unfollow_user(target_user) else log.warning(f'unable to unfollow {username}')
                                else:
                                    log.info(f'successfully turned off notification for {username} (due to client change)') if old_app.disable_user_notification(target_user) else log.warning(f'unable to turn off notifications for {username}')

                            await cursor.execute('REPLACE INTO user (client_used) VALUES (?) WHERE id = ?', (account_used, match_user['id']))
                            await cursor.execute('INSERT OR IGNORE INTO channel VALUES (?, ?)', (str(channel.id), server_id))
                            await cursor.execute('REPLACE INTO notification (user_id, channel_id, role_id, enable_type, enable_media_type) VALUES (?, ?, ?, ?, ?)', (match_user['id'], str(channel.id), roleID, enable_type, media_type))
                            await cursor.execute('UPDATE user SET enabled = 1 WHERE id = ?', (match_user['id'],))
                        else:
                            await itn.followup.send(f'user {username} already exists under {account_used}. No changes due to `auto_change_client` setting', ephemeral=True)
                            return

                    app.follow_user(new_user)

                    if app.enable_user_notification(new_user):
                        log.info(f'successfully turned on notification for {username}')
                    else:
                        log.warning(f'unable to turn on notifications for {username}')
                else:
                    await cursor.execute('INSERT OR IGNORE INTO channel VALUES (?, ?)', (str(channel.id), server_id))
                    await cursor.execute('REPLACE INTO notification (user_id, channel_id, role_id, enable_type, enable_media_type) VALUES (?, ?, ?, ?, ?)', (match_user['id'], str(channel.id), roleID, enable_type, media_type))

            await db.commit()

        if match_user is None or match_user['enabled'] == 0:
            await self.account_tracker.addTask(username, account_used)
            await itn.followup.send(f'successfully add notifier of {username} under {account_used}!', ephemeral=True)
        else:
            await itn.followup.send(f'{username} already exists under {match_user["client_used"]}. Using the same account to deliver notifications', ephemeral=True)

    @remove_group.command(name='notifier')
    async def r_notifier(self, itn: discord.Interaction, username: str, channel: discord.TextChannel):
        """Remove a notifier on your server.

        Parameters
        -----------
        username: str
            The username of the twitter user you want to turn off notifications for.
        channel: discord.TextChannel
            The channel which set to delivers notifications.
        """

        await itn.response.defer(ephemeral=True)

        async with aiosqlite.connect(os.path.join(os.getenv('DATA_PATH'), 'tracked_accounts.db')) as db:
            db.row_factory = aiosqlite.Row
            async with db.cursor() as cursor:

                await cursor.execute('SELECT user_id FROM notification, user WHERE username = ? AND channel_id = ? AND user_id = id AND notification.enabled = 1', (username, str(channel.id)))
                match_notifier = await cursor.fetchone()
                if match_notifier is not None:
                    await cursor.execute('UPDATE notification SET enabled = 0 WHERE user_id = ? AND channel_id = ?', (match_notifier['user_id'], str(channel.id)))
                    await db.commit()
                    await itn.followup.send(f'successfully remove notifier of {username}!', ephemeral=True)
                    await cursor.execute('SELECT user_id FROM notification WHERE user_id = ? AND enabled = 1', (match_notifier['user_id'],))

                    if await cursor.fetchone() is None:
                        await cursor.execute('UPDATE user SET enabled = 0 WHERE id = ?', (match_notifier['user_id'],))
                        await db.commit()
                        await self.account_tracker.removeTask(username)
                        if configs['auto_unfollow'] or configs['auto_turn_off_notification']:
                            await cursor.execute('SELECT client_used FROM user WHERE id = ?', (match_notifier['user_id'],))
                            result = await cursor.fetchone()
                            client_used = result['client_used']
                            app = Twitter(client_used)
                            app.load_auth_token(get_accounts()[client_used])
                            target_user = app.get_user_info(username)

                            if configs['auto_unfollow']:
                                log.info(f'successfully unfollowed {username}') if app.unfollow_user(target_user) else log.warning(f'unable to unfollow {username}')
                            else:
                                log.info(f'successfully turned off notification for {username}') if app.disable_user_notification(target_user) else log.warning(f'unable to turn off notifications for {username}')

                else:
                    await itn.followup.send(f'can\'t find notifier {username} in {channel.mention}!', ephemeral=True)

    @r_notifier.autocomplete('username')
    async def get_enabled_users(self, itn: discord.Interaction, username: str) -> list[app_commands.Choice[str]]:
        async with aiosqlite.connect(os.path.join(os.getenv('DATA_PATH'), 'tracked_accounts.db')) as db:
            db.row_factory = aiosqlite.Row
            async with db.cursor() as cursor:
                if username:
                    await cursor.execute('SELECT username FROM user WHERE username LIKE ? AND enabled = 1', (f'%{username}%',))
                else:
                    await cursor.execute('SELECT username FROM user WHERE enabled = 1')
                return [app_commands.Choice(name=row['username'], value=row['username']) async for row in cursor]

    @customize_group.command(name='message')
    async def customize_message(self, itn: discord.Interaction, username: str, channel: discord.TextChannel, default: bool = False):
        """Set customized messages for notification.

        Parameters
        -----------
        username: str
            The username of the twitter user you want to set customized message.
        channel: discord.TextChannel
            The channel which set to delivers notifications.
        default: bool
            Whether to use default setting.
        """

        async with aiosqlite.connect(os.path.join(os.getenv('DATA_PATH'), 'tracked_accounts.db')) as db:
            db.row_factory = aiosqlite.Row
            async with db.cursor() as cursor:

                await cursor.execute('SELECT user_id FROM notification, user WHERE username = ? AND channel_id = ? AND user_id = id AND notification.enabled = 1', (username, str(channel.id)))
                match_notifier = await cursor.fetchone()
                if match_notifier is not None:
                    if default:
                        await itn.response.defer(ephemeral=True)
                        await cursor.execute('UPDATE notification SET customized_msg = ? WHERE user_id = ? AND channel_id = ?', (None, match_notifier['user_id'], str(channel.id)))
                        await db.commit()
                        await itn.followup.send('successfully restored to default settings', ephemeral=True)
                    else:
                        modal = CustomizeMsgModal(match_notifier['user_id'], username, channel)
                        await itn.response.send_modal(modal)
                else:
                    await itn.response.send_message(f'can\'t find notifier {username} in {channel.mention}!', ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Notification(bot))
