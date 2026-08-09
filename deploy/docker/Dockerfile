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

# imps_dir in imps_config.toml MUST equal this path
ENV IMPS_HOME=/app
EXPOSE 80

# Matches run.py's own comment: "For production, run with gunicorn"
CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:80", "run:app"]
