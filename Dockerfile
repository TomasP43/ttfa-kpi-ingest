FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=America/Argentina/Buenos_Aires

# tzdata + cron para el modo programado
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata cron \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Volúmenes esperados para persistir entre corridas
VOLUME ["/app/state", "/app/output", "/app/downloads"]

ENTRYPOINT ["/entrypoint.sh"]
