# Running IMPS with Docker

This guide covers installing IMPS via Docker/Docker Compose, pulled from `airbornedan/IMPS`. It's intended for a private/home LAN — don't expose the app to the public internet. The IMPS readme file has more information about using IMPS.

## Requirements

* Docker Engine + Docker Compose plugin installed
* Nothing else — MariaDB runs in its own container, no host MySQL/MariaDB install needed

## 1. Get the repo

```bash
git clone https://github.com/airbornedan/IMPS.git
cd IMPS/deploy/docker
cp dockerfile ../../
cp docker-compose.yaml ../..
cp .env.example ../../.env
```

## 2. Configure your environment

Fill in your own values in the `.env` file:

```bash
nano .env
```

Edit `.env` to change the values from the defaults if desired:
```
MARIADB_ROOT_PASSWORD=mariadb_pass
IMPS_DB_PASSWORD=box_pass
IMPS_IP=192.168.1.50
```

* `MARIADB_ROOT_PASSWORD` / `IMPS_DB_PASSWORD` — pick any strong, unique values. Nothing else needs to match these except the containers themselves, which wire it up automatically.
* `IMPS_IP` — the LAN IP (or hostname) of the machine running Docker. This is what gets baked into the QR codes IMPS generates for each box, so it needs to be something _other devices on your network_ can actually reach — not `127.0.0.1` and not the container's internal IP. Your system running Docker should use a fixed IP address, not DHCP.

## 3. Start it

```bash
docker compose up -d
```

First boot does a few things automatically:

* MariaDB initializes its data directory, creates the `box_db` database and a `box_user` account scoped to accept connections from the app container
* IMPS's config file is generated from a template using the values in `.env` — no manual editing required
* Compose waits for MariaDB to report itself healthy before starting IMPS, so there's no race between the two containers on first boot

Give it 10–20 seconds on the first run for MariaDB's initialization to finish.

## 4. Finish setup in the browser

Go to `http://<IMPS_IP>/` (or `http://localhost/` if you're on the same machine). You'll land on the setup wizard automatically:

1. **Database status** — should already show connected
2. **Create tables** — one click, builds the schema
3. **Sample data** — optional, purely cosmetic starter items
4. **Set your password** — replaces the placeholder login password with a real one you choose. This is the shared password everyone on your LAN will use to log in.

Once you set the password, setup is locked and `/` shows the normal login page from then on.

## Data persistence

Your inventory data, uploaded photos, generated QR codes, and DB/photo backups all live in Docker volumes and survive container restarts, rebuilds, and `docker compose down` (without `-v`). The only things that get rebuilt from scratch are the application code and config generation — none of your actual inventory data.

## Stopping / restarting

```bash
docker compose stop      # stop containers, keep everything
docker compose up -d     # start them again
docker compose down      # remove containers, keep volumes/data
```

Avoid `docker compose down -v` unless you genuinely want to wipe your database and start over — it deletes the named volumes, including your inventory data.

## Updating to a newer version

```bash
git pull
docker compose build imps
docker compose up -d
```

This only rebuilds the app image — your database and uploaded photos are untouched, since they live in separate volumes, not in the image.

## Troubleshooting

**Nothing loads at `http://<IMPS_IP>/`**

```bash
docker compose ps
```

Confirm both containers show `Up`, and that the `imps` container shows a port mapping like `0.0.0.0:80->80/tcp`.

**Check logs if something looks wrong:**

```bash
docker compose logs imps
docker compose logs mariadb
```

**First run only: if you ever see a database connection error**, it's almost always MariaDB still finishing its first-time initialization — wait a bit and check `docker compose logs mariadb` for `ready for connections`, then IMPS will connect automatically on its own retry (no restart needed).

**If you need to start completely fresh** (wipes all data — only do this intentionally):

```bash
docker compose down -v
docker compose up -d
```

