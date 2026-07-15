#!/usr/bin/env python3
########################################################################
### IMPS DEMO RESET
########################################################################
# Restores the database and item-image directory to a fixed "seed" state.
# Intended to run on a schedule (systemd timer / cron) against a public
# demo instance, so visitors always start from a clean, curated inventory.
#
# WHAT IT DOES, IN ORDER:
#   1. Acquire a lockfile so two reset runs can't overlap.
#   2. Put the app into maintenance mode (optional -- see MAINTENANCE_FLAG).
#   3. Drop and reload the database from the seed .sql dump.
#   4. Extract SEED_IMAGES_ZIP into a staging directory, then atomically
#      swap it in to replace the live item-image directory.
#   5. Remove the maintenance flag.
#
# IMAGE SEEDING: comes from a single zip file (SEED_IMAGES_ZIP)
# containing ONLY flat image files -- no subdirectories, no config, no
# credentials. Extraction explicitly rejects anything that isn't a
# plain top-level file (see _safe_zip_members below): directory
# entries, nested paths, and any path-traversal attempt (e.g.
# "../../etc/passwd") are all refused, and the whole reset aborts
# rather than silently skipping a bad entry.
#
# CREDENTIALS: this script uses a separate, minimally-privileged DB user
# (box_reset), never the app's own DB user. See RESET_CONFIG_FILE below.
# That account should live ONLY in a config file with tight (600)
# permissions, kept well away from any directory the reset script also
# writes seed content into.
#
#   CREATE USER 'box_reset'@'localhost' IDENTIFIED BY 'some-strong-password';
#   GRANT DROP, CREATE, ALTER, INDEX, CREATE VIEW, LOCK TABLES,
#         INSERT, SELECT, UPDATE, DELETE ON box_db.* TO 'box_reset'@'localhost';
#   FLUSH PRIVILEGES;
#
# SETUP (one-time):
#   1. Dump the seed DB (from a known-good live state):
#        mysqldump --single-transaction --skip-lock-tables -u box_user -p box_db \
#          > /var/www/getimps.com/demo/deploy/seed_db.sql
#   2. Build a FLAT zip of just the image files (no folders):
#        cd /var/www/getimps.com/demo/static/images/items && \
#          zip -j /var/www/getimps.com/demo/deploy/seed_images.zip *
#      The -j ("junk paths") flag is what guarantees a flat archive --
#      double check with `unzip -l seed_images.zip` that every entry is
#      a bare filename with no "/" in it before trusting the archive.
#   3. Create the reset-only MySQL user (see SQL above) and fill in
#      reset_credentials.toml (chmod 600) -- see RESET_CONFIG_FILE below.
#   4. Test manually: python3 imps_reset.py --dry-run
#   5. Wire up the systemd timer (imps-reset.timer / imps-reset.service).
#
# --- reset_credentials.toml format ---
#   [reset_database]
#   user = "box_reset"
#   password = "some-strong-password"
#   host = "localhost"
########################################################################

import argparse
import grp
import os
import pwd
import shutil
import subprocess
import sys
import tempfile
import time
import fcntl
import zipfile
import toml

########################################################################
### CONFIG -- adjust these paths for your install
########################################################################

CONFIG_FILE = "/var/www/getimps.com/demo/imps_config.toml"                     # app config (db name + image paths only -- NOT credentials)
RESET_CONFIG_FILE = "/var/www/getimps.com/demo/deploy/reset_credentials.toml"  # separate, reset-only DB credentials
SEED_DB_DUMP = "/var/www/getimps.com/demo/deploy/seed_db.sql"                  # output of mysqldump
SEED_IMAGES_ZIP = "/var/www/getimps.com/demo/deploy/seed_images.zip"           # FLAT zip of image files only -- see SETUP step 2 above
LOCK_FILE = "/tmp/imps_reset.lock"
MAINTENANCE_FLAG = "/var/www/getimps.com/demo/deploy/MAINTENANCE"

# The user/group the web app actually runs as (see WSGIDaemonProcess in
# your Apache config). This script may be run manually as root (e.g.
# while testing) OR via the systemd timer -- regardless of who invokes
# it, the extracted image directory is explicitly chown'd to this
# owner before going live. This is what happened when this script was
# run manually as root: the resulting directory ended up root-owned,
# and www-data (the app) couldn't write OR delete anything in it
# afterward, since deleting a file requires write permission on its
# containing directory, not just the file itself.
TARGET_OWNER = "www-data"
TARGET_GROUP = "www-data"

# Sanity caps on the seed zip, so a corrupted/wrong archive fails loudly
# instead of doing something unexpected. Adjust if your real seed set is
# larger than this.
MAX_SEED_IMAGE_FILES = 2000
MAX_SEED_IMAGE_TOTAL_BYTES = 500 * 1024 * 1024  # 500 MB


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_app_config():
    """DB name/host and image paths -- read-only info about the app's
    setup. Deliberately does NOT supply credentials; see
    load_reset_credentials().

    NOTE: the [directories] key is 'imps_dir', not 'imps_path' -- see
    imps_config.toml.example and app/extensions.py's IMPS_DIR, which
    reads this same key. A prior version of this function read
    'imps_path', which doesn't exist in imps_config.toml and raised a
    KeyError on every single run.
    """
    with open(CONFIG_FILE) as f:
        cfg = toml.load(f)
    return cfg["database"], cfg["directories"]["item_image_dir"], cfg["directories"]["imps_dir"]


def load_reset_credentials():
    """The separate, minimally-privileged user used ONLY by this script."""
    if not os.path.isfile(RESET_CONFIG_FILE):
        raise SystemExit(
            f"Reset credentials file not found: {RESET_CONFIG_FILE}\n"
            "See the header comment in this file for the CREATE USER/GRANT "
            "statements and the expected reset_credentials.toml format."
        )
    mode = os.stat(RESET_CONFIG_FILE).st_mode & 0o777
    if mode & 0o077:
        log(f"  WARNING: {RESET_CONFIG_FILE} is readable/writable by group or others "
            f"(mode {oct(mode)}). Run: chmod 600 {RESET_CONFIG_FILE}")
    with open(RESET_CONFIG_FILE) as f:
        cfg = toml.load(f)
    return cfg["reset_database"]


def run_mysql(args, reset_creds, stdin=None):
    env = os.environ.copy()
    env["MYSQL_PWD"] = reset_creds["password"]
    cmd = ["mysql", "-h", reset_creds["host"], "-u", reset_creds["user"]] + args
    return subprocess.run(cmd, env=env, stdin=stdin, check=True)


def reset_database(dbname, reset_creds, dry_run):
    log(f"Resetting database '{dbname}' from {SEED_DB_DUMP}")

    if not os.path.isfile(SEED_DB_DUMP):
        raise SystemExit(f"Seed DB dump not found: {SEED_DB_DUMP}")

    if dry_run:
        log("  [dry-run] would DROP DATABASE + reload from seed dump")
        return

    drop_create_sql = f"DROP DATABASE IF EXISTS `{dbname}`; CREATE DATABASE `{dbname}`;"
    with tempfile.NamedTemporaryFile(mode="w", suffix=".sql") as f:
        f.write(drop_create_sql)
        f.flush()
        with open(f.name) as sql_in:
            run_mysql([], reset_creds, stdin=sql_in)

    with open(SEED_DB_DUMP) as sql_in:
        run_mysql([dbname], reset_creds, stdin=sql_in)

    log("  Database reset complete.")


def _safe_zip_members(zf):
    """Validate every entry in the seed zip before trusting any of it.

    Rejects the whole archive (raises SystemExit) rather than silently
    skipping a bad entry, if ANY of the following are found:
      - a directory entry
      - a name containing "/" or "\\" (i.e. anything not a flat,
        top-level file -- this is what guarantees the extracted result
        can only ever be image files, never a nested folder structure
        or something that lands outside the target directory)
      - a name containing ".." (defense in depth against path traversal,
        even though the "/" check above already rules out crossing
        directories in a flat zip)
      - a hidden/dotfile name (not a real image; almost certainly a
        mistake, e.g. .DS_Store from macOS)
    """
    names = []
    total_uncompressed = 0

    for info in zf.infolist():
        name = info.filename

        if info.is_dir() or name.endswith("/"):
            raise SystemExit(f"Seed zip contains a directory entry ('{name}') -- must be a flat zip of files only.")
        if "/" in name or "\\" in name:
            raise SystemExit(f"Seed zip contains a nested path ('{name}') -- must be a flat zip (build it with `zip -j`).")
        if ".." in name:
            raise SystemExit(f"Seed zip contains a suspicious entry ('{name}') -- refusing to extract.")
        if name.startswith("."):
            raise SystemExit(f"Seed zip contains a hidden file ('{name}') -- remove it from the archive and retry.")

        names.append(name)
        total_uncompressed += info.file_size

    if not names:
        raise SystemExit("Seed zip is empty.")
    if len(names) > MAX_SEED_IMAGE_FILES:
        raise SystemExit(f"Seed zip has {len(names)} files, more than the expected cap of {MAX_SEED_IMAGE_FILES}. Refusing to extract -- check you built the right archive.")
    if total_uncompressed > MAX_SEED_IMAGE_TOTAL_BYTES:
        raise SystemExit(f"Seed zip would extract to {total_uncompressed} bytes, more than the expected cap of {MAX_SEED_IMAGE_TOTAL_BYTES}. Refusing to extract.")

    return names


def _enforce_ownership(tmp_new, names):
    """Make sure the extracted files (and the directory itself) end up
    owned by TARGET_OWNER/TARGET_GROUP -- the user the web app actually
    runs as -- regardless of which user actually ran this script.

    Only root can chown() a file to a different owner at all (this is a
    POSIX restriction, not specific to this script). So:
      - If we ARE root, actively chown everything to the target.
      - If we're NOT root, we can't force it -- instead, verify the
        files already came out owned correctly (which they will, if
        this script is invoked the intended way: via the systemd
        service running as TARGET_OWNER) and warn loudly if not,
        rather than silently producing a directory the app can't
        write to -- which is exactly what happened when this script
        was run manually as root in the first place.
    """
    try:
        target_uid = pwd.getpwnam(TARGET_OWNER).pw_uid
        target_gid = grp.getgrnam(TARGET_GROUP).gr_gid
    except KeyError as e:
        log(f"  WARNING: could not resolve TARGET_OWNER/TARGET_GROUP ({e}) -- skipping ownership enforcement.")
        return

    paths = [tmp_new] + [os.path.join(tmp_new, name) for name in names]

    if os.geteuid() == 0:
        for path in paths:
            os.chown(path, target_uid, target_gid)
        log(f"  Set ownership of extracted files to {TARGET_OWNER}:{TARGET_GROUP}.")
    else:
        current_uid = os.geteuid()
        if current_uid != target_uid:
            log(f"  WARNING: running as uid {current_uid}, not '{TARGET_OWNER}' (uid {target_uid}), "
                f"and not root -- cannot fix ownership. The live image directory may end up "
                f"owned by the wrong user, which will break uploads/deletes in the app. "
                f"Run this script as root, or as {TARGET_OWNER}, not any other user.")


def reset_images(image_dir_abs, dry_run):
    log(f"Resetting image directory '{image_dir_abs}' from {SEED_IMAGES_ZIP}")

    if not os.path.isfile(SEED_IMAGES_ZIP):
        raise SystemExit(f"Seed images zip not found: {SEED_IMAGES_ZIP}")

    with zipfile.ZipFile(SEED_IMAGES_ZIP) as zf:
        names = _safe_zip_members(zf)
        log(f"  Seed zip contains {len(names)} flat image file(s) -- validated OK.")

        if dry_run:
            log("  [dry-run] would replace live image dir with these files")
            return

        parent = os.path.dirname(image_dir_abs.rstrip("/"))
        tmp_new = os.path.join(parent, ".images_new_" + str(int(time.time())))
        tmp_old = os.path.join(parent, ".images_old_" + str(int(time.time())))

        os.makedirs(tmp_new, exist_ok=False)
        zf.extractall(tmp_new, members=names)

        # Belt-and-suspenders: confirm every extracted path actually
        # landed directly inside tmp_new (not e.g. resolved somewhere
        # else via a symlink or an extraction quirk) before swapping it
        # into place as the live directory.
        tmp_new_real = os.path.realpath(tmp_new)
        for name in names:
            extracted_path = os.path.realpath(os.path.join(tmp_new, name))
            if os.path.dirname(extracted_path) != tmp_new_real:
                shutil.rmtree(tmp_new, ignore_errors=True)
                raise SystemExit(f"Extracted file landed outside the staging directory ('{name}') -- aborting, nothing was swapped in.")

        _enforce_ownership(tmp_new, names)

    # Atomic swap: live -> old, new -> live. Same rationale as before --
    # both renames are atomic on the same filesystem, so a crash between
    # them is the only way to see a half-swapped state, and even then
    # the live path is briefly *missing* rather than partially wrong.
    os.rename(image_dir_abs, tmp_old)
    os.rename(tmp_new, image_dir_abs)
    shutil.rmtree(tmp_old)

    log("  Image directory reset complete.")


def main():
    parser = argparse.ArgumentParser(description="Reset IMPS demo DB + images to seed state.")
    parser.add_argument("--dry-run", action="store_true", help="Log what would happen without changing anything.")
    args = parser.parse_args()

    lock_fd = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("Another reset is already running -- exiting.")
        sys.exit(1)

    try:
        app_db_conf, item_image_dir_rel, imps_dir = load_app_config()
        reset_creds = load_reset_credentials()
        dbname = app_db_conf["name"]
        # os.path.join rather than string concatenation -- doesn't
        # silently depend on imps_dir ending in "/" the way
        # `imps_path + item_image_dir_rel` did. Same convention
        # app/extensions.py already uses for ITEM_IMAGE_FS_DIR.
        image_dir_abs = os.path.join(imps_dir, item_image_dir_rel)

        if not args.dry_run:
            open(MAINTENANCE_FLAG, "w").close()

        try:
            reset_database(dbname, reset_creds, args.dry_run)
            reset_images(image_dir_abs, args.dry_run)
        finally:
            if not args.dry_run and os.path.exists(MAINTENANCE_FLAG):
                os.remove(MAINTENANCE_FLAG)

        log("Reset finished successfully." if not args.dry_run else "Dry run finished.")

    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
