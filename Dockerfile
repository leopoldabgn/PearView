FROM python:3.11-slim

# cron : pour relancer generate_config.py toutes les 5 minutes
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Code de l'application (pas les données : data/ est monté en volume depuis l'hôte)
COPY server.py generate_config.py index.html favicon.ico /app/
COPY lib/ /app/lib/

# Structure par défaut si aucun volume n'est monté
RUN mkdir -p /app/data/assets /app/data/backups

# Cron job : régénère data/config.json toutes les 5 min à partir de data/assets/
COPY pearview-cron /etc/cron.d/pearview-cron
RUN chmod 0644 /etc/cron.d/pearview-cron \
    && crontab /etc/cron.d/pearview-cron \
    && touch /var/log/cron.log

COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 1500

ENTRYPOINT ["/app/entrypoint.sh"]