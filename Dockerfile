FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY discord_bot.py migrate_legacy_users.py legacy_user_import.py ./

USER 10001:10001

CMD ["python", "discord_bot.py"]
