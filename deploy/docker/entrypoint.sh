#!/bin/sh
### State lives in /data (config, secret key, setup marker, photos, QR codes, backups).
### First start writes the config from the environment and arms the setup wizard.
set -e

mkdir -p /data/static/images/items /data/static/images/qrcodes /data/static/backup
[ -f /data/static/images/items/none.jpg ] || cp /app/seed/none.jpg /data/static/images/items/none.jpg

if [ ! -f /data/imps_config.toml ]; then
    : "${IMPS_DB_PASSWORD:?IMPS_DB_PASSWORD is not set (see .env)}"
    : "${IMPS_IP:?IMPS_IP is not set: the LAN address other devices use to reach IMPS (see .env)}"
    python - <<'EOF'
import os, toml
toml.dump({
    "database": {
        "host": os.environ.get("IMPS_DB_HOST", "mariadb"),
        "name": os.environ.get("IMPS_DB_NAME", "box_db"),
        "user": os.environ.get("IMPS_DB_USER", "box_user"),
        "password": os.environ["IMPS_DB_PASSWORD"],
    },
    "directories": {
        "imps_ip": os.environ["IMPS_IP"],
        "imps_dir": "/data/",
        "item_image_dir": "static/images/items/",
        "backup_dir": "static/backup",
    },
    "password": {"password": "imps"},
    "instance": {"label": os.environ.get("IMPS_LABEL", "")},
}, open("/data/imps_config.toml", "w"))
EOF
    touch /data/first.run
    echo "IMPS: new install -- open http://${IMPS_IP}/ to finish setup."
fi

exec "$@"
