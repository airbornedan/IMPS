FROM python:3.12-slim

# libjpeg/zlib for Pillow's image handling; default-mysql-client gives us
# mysqldump for the in-app backup feature (cp_backupnow route).
RUN apt-get update && apt-get install -y --no-install-recommends \
        libjpeg62-turbo zlib1g default-mysql-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run-time state lives in the /data volume (imps_dir); static paths link into it.
RUN mkdir -p seed \
    && mv static/images/items/none.jpg seed/ \
    && rm -rf static/images/items static/images/qrcodes static/backup first.run imps_config.toml \
    && ln -s /data/static/images/items static/images/items \
    && ln -s /data/static/images/qrcodes static/images/qrcodes \
    && ln -s /data/static/backup static/backup \
    && ln -s /data/imps_config.toml imps_config.toml \
    && install -m 755 deploy/docker/entrypoint.sh /usr/local/bin/imps-entrypoint

ENV IMPS_HOME=/app
VOLUME /data
EXPOSE 80

ENTRYPOINT ["imps-entrypoint"]
# One worker: login rate limiting and maintenance mode keep state in-process.
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:80", "run:app"]
