FROM python:3.11-slim

# cron: to rerun generate_config.py every 5 minutes
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Application code (not the data: data/ is mounted as a volume from the host)
COPY server.py generate_config.py index.html favicon.ico /app/
COPY lib/ /app/lib/

# Default structure if no volume is mounted
RUN mkdir -p /app/data/assets /app/data/backups

# Cron job: regenerates data/config.json every 5 min from data/assets/
COPY pearview-cron /etc/cron.d/pearview-cron
RUN chmod 0644 /etc/cron.d/pearview-cron \
    && crontab /etc/cron.d/pearview-cron \
    && touch /var/log/cron.log

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 1500

ENTRYPOINT ["/app/entrypoint.sh"]