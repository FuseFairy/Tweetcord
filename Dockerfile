FROM python:3.11.13
LABEL org.opencontainers.image.source="https://github.com/Yuuzi261/Tweetcord"
LABEL org.opencontainers.image.description="A Discord bot for Twitter notifications, using tweety-ns module."
LABEL org.opencontainers.image.licenses="MIT"
WORKDIR /bot
COPY requirements.txt /bot/
RUN pip install -r requirements.txt
RUN pip install --no-cache-dir --upgrade --force-reinstall git+https://github.com/mahrtayyab/tweety.git
COPY . /bot
CMD ["python", "bot.py"]