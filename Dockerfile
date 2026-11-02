FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 DB_PATH=/app/data/tracker.sqlite3

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot

# Бот работает не от root: при взломе у него будет меньше прав.
RUN useradd --create-home bot && mkdir data && chown bot:bot data
USER bot

CMD ["python", "-m", "bot.main"]
