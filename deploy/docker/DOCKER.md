# Running IMPS with Docker

IMPS is for a private home LAN. Don't expose it to the public internet. The IMPS README has more about using IMPS.

The image is `ghcr.io/airbornedan/imps` (amd64 and arm64, so a 64-bit Raspberry Pi works). MariaDB runs in its own container; nothing else needs installing besides Docker Engine with the Compose plugin.

## 1. Run these three commands

These create `~/imps` and download the two setup files into it.

```bash
mkdir -p ~/imps && cd ~/imps
curl -fsSLO https://raw.githubusercontent.com/airbornedan/IMPS/main/deploy/docker/docker-compose.yml
curl -fsSL -o .env https://raw.githubusercontent.com/airbornedan/IMPS/main/deploy/docker/.env.example
```

## 2. Edit ~/imps/.env with a text editor

```
IMPS_IP=192.168.1.50
IMPS_PORT=80
MARIADB_ROOT_PASSWORD=change-me-root
IMPS_DB_PASSWORD=change-me-imps
IMPS_LABEL=
```

* `IMPS_IP`: the LAN address (or hostname) other devices use to reach the Docker host. It's printed into every box's QR code, so not `127.0.0.1` or a container address. Give the host a fixed IP. If `IMPS_PORT` isn't 80, include the port: `192.168.1.50:8080`.
* `MARIADB_ROOT_PASSWORD`, `IMPS_DB_PASSWORD`: pick your own strong values. Only the two containers use them.
* `IMPS_LABEL`: optional; shown next to "IMPS" in the header.

## 3. Run the Docker command

Run this from the `~/imps` directory used in step 1:

```bash
docker compose up -d
```

On first start MariaDB creates the `box_db` database and its user, IMPS writes its config from `.env`, and Compose waits for MariaDB to be healthy before starting IMPS. Allow 10–20 seconds.

## 4. Finish setup in the browser

Open `http://<IMPS_IP>/`. The setup wizard runs once:

1. **Database status**: should show connected.
2. **Create tables**: one click.
3. **Sample data**: optional starter items.
4. **Set your password**: the shared password everyone on your LAN uses to log in.

After that, `/` shows the login page.

## Data

Two volumes hold everything: `db_data` (the database) and `imps_data` (config, item photos, QR codes, backups). They survive restarts, updates and `docker compose down`. `docker compose down -v` deletes them, along with your inventory.

`.env` is only read on the first start. To change the IP or the database password later, edit `imps_config.toml` in the `imps_data` volume:

```bash
docker compose cp imps:/data/imps_config.toml .
# edit imps_config.toml, then:
docker compose cp imps_config.toml imps:/data/imps_config.toml
docker compose restart imps
```

## Updating

```bash
docker compose pull
docker compose up -d
```

## Stopping

```bash
docker compose stop      # stop, keep everything
docker compose down      # remove containers, keep data
```

## Building the image yourself

From a clone of the repo:

```bash
git clone https://github.com/airbornedan/IMPS.git
cd IMPS/deploy/docker
cp .env.example .env     # then edit it
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

## Troubleshooting

* `docker compose ps`: both containers should be `Up`, IMPS with a port mapping such as `0.0.0.0:80->80/tcp`.
* `docker compose logs imps` / `docker compose logs mariadb`.
* A database error on the very first start usually means MariaDB is still initialising; wait for `ready for connections` in its log.
* Port 80 already taken: set `IMPS_PORT=8080` and `IMPS_IP=<ip>:8080` before the first start.
