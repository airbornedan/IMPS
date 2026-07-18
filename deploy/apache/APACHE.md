# Running IMPS under Apache

This picks up right where the main install instructions leave off: you've
got IMPS's files in `/var/www`, `imps_config.toml` filled in, the database
set up (`sudo python3 deploy/db_setup.py`), and you've confirmed it works
by running `python3 run.py` and hitting `http://<host>:88/`. This guide
gets the same app running under Apache instead, on the standard port 80,
so it starts automatically and stays running as long as Apache is running
— no terminal window, no manually re-running `run.py` after a reboot.

If you haven't done the steps above yet, do those first.

## 1. Stop the manual test run

If `python3 run.py` is still running in a terminal from testing, stop it
(Ctrl-C). It's not strictly required — it listens on port 88, Apache will
listen on port 80, so they wouldn't conflict directly — but there's no
reason to leave a second, unmanaged copy of the app running once Apache
takes over.

## 2. Install Apache and mod_wsgi

```bash
sudo apt update
sudo apt install apache2 libapache2-mod-wsgi-py3
sudo a2enmod wsgi
```

## 3. Enable the IMPS site

`imps-apache.conf` and `adapter.wsgi` already ship in `deploy/apache/` —
no need to move or copy `adapter.wsgi` anywhere; the config points
directly at it in place.

```bash
sudo cp /var/www/deploy/apache/imps-apache.conf /etc/apache2/sites-available/imps.conf
sudo a2ensite imps.conf
```

If nothing else is using Apache's default site on port 80, disable it so
it doesn't conflict:
```bash
sudo a2dissite 000-default.conf
```

**If your install isn't at `/var/www`**, edit
`/etc/apache2/sites-available/imps.conf` and change every path in it to
match — and make sure that same path is also what `imps_dir` is set to in
`imps_config.toml`. The app checks that these agree on startup and refuses
to run if they don't (see the "IMPS CONFIGURATION ERROR" message if you
ever see it) — see the [directory-path gotcha](#directory-path-gotcha)
below.

## 4. Fix file permissions

This is the single most common thing that trips people up here, so don't
skip it. Apache's worker process runs as the `www-data` user, not
whichever user you used to run the install steps — so `www-data` needs
its own read/write access to specific parts of the app:

```bash
sudo chown -R www-data:www-data /var/www/static/images
sudo chown -R www-data:www-data /var/www/static/backup
sudo chown www-data:www-data /var/www/.secret_key
sudo chmod 600 /var/www/.secret_key
```

**Why `.secret_key` specifically matters**: it's created automatically the
first time IMPS runs (that's what your `python3 run.py` test in step 0
already did), owned by whichever user ran that command — almost certainly
not `www-data`. If Apache can't read it, the app fails immediately on
startup with a permissions error. If you hit that, this step is almost
always why.

## 5. Start it

```bash
sudo systemctl restart apache2
```

Apache is enabled to start on boot by default on Debian/Ubuntu after
`apt install`, so this is also the point where IMPS becomes something
that survives a reboot without you doing anything else — no separate
step needed to "install it as a service."

## 6. Verify

```bash
sudo apachectl configtest
curl -I http://localhost/
```
`configtest` should say `Syntax OK`. The `curl` should return a `200` or a
redirect to `/setup` if this is a fresh install that hasn't finished the
setup wizard yet. From another device on the same network, use the
server's actual IP or hostname instead of `localhost`.

If either of those doesn't look right, check the logs:
```bash
sudo tail -f /var/log/apache2/imps_error.log
```

---

## Directory-path gotcha

Three separate things all need to agree on the exact same absolute path,
or the app fails at startup with a clear (if occasionally confusing)
error:

| Where | What it must say |
|---|---|
| Actual file location | e.g. `/var/www` |
| `imps_config.toml` → `[directories] imps_dir` | must match, exactly |
| `imps-apache.conf` → `python-path=`, `WSGIScriptAlias` target, `<Directory>` | must match, exactly |

`adapter.wsgi` itself doesn't need editing even if you move things around
relative to it — its `os.chdir(...)`/`sys.path.insert(...)` calls are
what actually encode "where the app lives," and those already say
`/var/www`. Only the *config* needs to change if you install somewhere
else; `adapter.wsgi` and `imps-apache.conf` need to describe the same
place, not necessarily where `adapter.wsgi` itself is stored on disk.

## Updating IMPS later

```bash
sudo systemctl stop apache2
# pull/copy in the new files
sudo systemctl start apache2
```
Your database and uploaded photos live outside the application code
(MariaDB's own data directory, `static/images/items/`), so a normal code
update doesn't touch them.

## Troubleshooting checklist

- **"IMPS CONFIGURATION ERROR" about `imps_dir`** — the three-way path
  agreement above is off somewhere. Double check all three.
- **App fails at startup, no clear error, or a permissions-looking
  traceback in `imps_error.log`** — almost always `.secret_key`
  ownership (step 4).
- **`curl -I http://localhost/` connects but hangs or 500s** — check
  `imps_error.log` first; if it mentions a database error, confirm
  `deploy/db_setup.py` was run and `imps_config.toml`'s `[database]`
  section has the right credentials.
- **Apache won't start at all** — `sudo apachectl configtest` first,
  it'll usually point straight at the broken line.
