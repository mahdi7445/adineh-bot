FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 TZ=Asia/Tehran
RUN useradd -m -u 10001 bot
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot ./bot
COPY tools ./tools
RUN mkdir -p /app/data && chown -R bot:bot /app
USER bot
CMD ["python", "-m", "bot.main"]
