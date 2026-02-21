FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    cron curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app

# Set up sync script and cron job - 5am daily
RUN chmod +x /app/sync.sh \
    && echo "0 5 * * * /app/sync.sh" > /etc/cron.d/followmee-sync \
    && chmod 0644 /etc/cron.d/followmee-sync \
    && crontab /etc/cron.d/followmee-sync \
    && touch /var/log/sync.log

CMD ["/bin/sh", "-c", "cron && tail -f /var/log/sync.log"]
