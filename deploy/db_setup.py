#!/usr/bin/env python3
########################################################################
### IMPS DATABASE SETUP
########################################################################
# One-time, root-privileged provisioning: creates the MySQL/MariaDB
# database and user account IMPS runs as, and grants that user just
# enough privilege to manage its own tables. Run this ONCE, after
# imps_config.toml exists and BEFORE visiting /setup in a browser.
#
# WHAT THIS DOES NOT DO: create IMPS's tables. That happens in the
# /setup web wizard (app/blueprints/setup.py) the first time you log
# in. Handled there rather than here because box_user (the account
# this script creates) is already granted CREATE/DROP/ALTER on its own
# database -- table creation doesn't need root, so it belongs in the
# app, where it can also detect and prompt before overwriting a
# database that already has real data (this script has no way to know
# about that). Nothing here touches schema.sql.
#
# WHY THIS ISN'T PART OF THE APP ITSELF: the account IMPS runs as
# (box_user, by default) is deliberately scoped to box_db.* only -- it
# can manage its own tables, but can't create other databases or
# users. That requires the MySQL/MariaDB root account, and the /setup
# wizard's routes are reachable over the network with no login yet
# (no password to check until setup finishes) -- see the docstring at
# the top of app/blueprints/setup.py. Handing root DB credentials to
# code behind an unauthenticated web route would erase that safety
# boundary, so this stays a separate script that only runs at the
# terminal, by whoever already has root/sudo on the machine.
#
# CREDENTIALS: reads the target database name/user/password straight
# out of imps_config.toml's [database] section -- whatever's already
# there -- so there's exactly one place those values live, not a
# second copy to keep in sync. Root access to the DB server itself is
# obtained via passwordless sudo/unix_socket auth (the default for a
# fresh Debian/Ubuntu MariaDB install), no prompt needed in the common
# case; otherwise falls back to prompting for root DB credentials
# interactively (never stored, never passed as a command-line
# argument, never logged).
#
# USAGE (from the IMPS install root, i.e. the same directory
# imps_config.toml lives in):
#   cd deploy
#   sudo python3 db_setup.py
#
# Safe to re-run: every statement below is idempotent (CREATE USER/
# DATABASE IF NOT EXISTS, GRANT is naturally idempotent), so running
# this again after a partial failure -- or just to double check
# everything's in place -- won't error out, duplicate anything, or
# touch any existing tables/data.
########################################################################

import getpass
import os
import sys

import toml

try:
    import mysql.connector
    from mysql.connector import errorcode
except ImportError:
    sys.exit(
        "mysql-connector-python isn't installed in this environment.\n"
        "Activate the venv first: source .venv/bin/activate\n"
        "(It's already listed in requirements.txt -- if it's still "
        "missing after activating, re-run: pip install -r requirements.txt)"
    )

### RESOLVED RELATIVE TO THIS SCRIPT'S OWN LOCATION, NOT THE CURRENT
### WORKING DIRECTORY -- this script lives in deploy/, alongside
### schema.sql/setup.sql, and is meant to be run as `cd deploy &&
### sudo python3 db_setup.py`, so a bare relative "imps_config.toml"
### would look in deploy/ and never find it.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
IMPS_ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(IMPS_ROOT, "imps_config.toml")

### The default Unix socket path for MariaDB on Debian/Ubuntu -- see
### _connect_as_root() below for why this matters.
DEFAULT_SOCKET = "/run/mysqld/mysqld.sock"

# Privileges box_user needs on its own database: enough to manage its
# own tables (including the /setup wizard's later CREATE TABLE calls),
# nothing that reaches outside box_db.* and nothing that can create
# other users or databases. REFERENCES is required because schema.sql's
# boxes/items tables declare foreign keys against categories/locations
# -- without it, table creation fails the moment it hits the first
# FOREIGN KEY constraint. Mirrors deploy/setup.sql exactly.
GRANT_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE, LOCK TABLES, CREATE, DROP, ALTER, INDEX, REFERENCES"


def _load_target_config():
    if not os.path.isfile(CONFIG_PATH):
        sys.exit(
            f"Couldn't find imps_config.toml at {CONFIG_PATH}.\n"
            "Make sure you've already copied imps_config.toml.example to "
            "imps_config.toml (in the IMPS install root, one level up "
            "from deploy/) and filled in the [database] section."
        )

    with open(CONFIG_PATH) as f:
        config = toml.load(f)

    try:
        db_config = config["database"]
        name = db_config["name"]
        user = db_config["user"]
        password = db_config["password"]
        host = db_config.get("host", "127.0.0.1")
    except KeyError as e:
        sys.exit(
            f"imps_config.toml is missing the [database] setting {e}.\n"
            "Fill in the [database] section completely before running this script."
        )

    if not name or not user or not password:
        sys.exit(
            "The [database] name/user/password fields in imps_config.toml "
            "are blank. Fill them in with the values you want IMPS's "
            "database account to use, then re-run this script."
        )

    return host, name, user, password


def _prompt_for_root_credentials(db_host):
    print(f"Connecting to the MySQL/MariaDB server at '{db_host}' as root.")
    print("This password is used once, for this script, and is never stored.\n")
    root_user = input("Root (or other admin) DB username [root]: ").strip() or "root"
    root_password = getpass.getpass("Root DB password: ")
    return root_user, root_password


def _connect_as_root(db_host):
    ### ON A FRESH DEBIAN/UBUNTU MARIADB INSTALL, root@localhost uses
    ### the unix_socket auth plugin by default -- it checks that the
    ### connecting OS user is literally "root", not a password. Since
    ### this script is meant to be run as `sudo python3 db_setup.py`,
    ### that's exactly the identity making the connection, so this
    ### should just work with no prompt at all in the common case.
    ###
    ### Root is only needed for the socket-auth attempt below. A remote
    ### db_host, or a local one without the socket, skip straight to
    ### the password prompt instead, which needs no local privilege.
    attempting_socket_auth = db_host in ("localhost", "127.0.0.1") and os.path.exists(DEFAULT_SOCKET)

    if attempting_socket_auth:
        if os.geteuid() != 0:
            sys.exit(
                "This script needs root privileges to create the database "
                "and user account.\nRe-run as: sudo python3 db_setup.py"
            )
        try:
            conn = mysql.connector.connect(unix_socket=DEFAULT_SOCKET, user="root")
            print("Connected as root via passwordless socket auth (sudo).\n")
            return conn
        except mysql.connector.Error:
            print(
                "Passwordless root access via socket auth didn't work "
                "(root's auth may have been changed by mysql_secure_installation, "
                "or this isn't a Debian/Ubuntu-style install) -- falling back "
                "to a password prompt.\n"
            )

    root_user, root_password = _prompt_for_root_credentials(db_host)
    try:
        return mysql.connector.connect(
            host=db_host, user=root_user, password=root_password
        )
    except mysql.connector.Error as e:
        if e.errno == errorcode.ER_ACCESS_DENIED_ERROR:
            sys.exit(
                "Access denied -- that username/password wasn't accepted "
                f"by the DB server at '{db_host}'. Double check the "
                "credentials and try again."
            )
        sys.exit(
            f"Couldn't connect to the DB server at '{db_host}': {e}\n"
            "Is MariaDB/MySQL installed and running?"
        )


def _provision(root_conn, db_host, db_name, db_user, db_password):
    cursor = root_conn.cursor()

    print(f"Creating user '{db_user}'@'localhost' (if not already present)...")
    # Host is deliberately hardcoded to 'localhost' here, matching
    # setup.sql -- IMPS and the database are expected to be on the
    # same machine (README's Raspberry Pi / single-server setup), and
    # scoping the account to localhost only means it can't be used to
    # log in to this database from anywhere else on the network, even
    # if the credentials ever leaked.
    cursor.execute(
        "CREATE USER IF NOT EXISTS %s@'localhost' IDENTIFIED BY %s",
        (db_user, db_password),
    )

    print(f"Creating database '{db_name}' (if not already present)...")
    # Database name can't be parameterized in MySQL/MariaDB the way
    # values can -- it's identifier position, not a literal. Backtick-
    # quoted and validated below instead.
    _assert_safe_identifier(db_name, "database name")
    cursor.execute(
        f"CREATE DATABASE IF NOT EXISTS `{db_name}` "
        "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci"
    )

    print(f"Granting '{db_user}' access to '{db_name}' only...")
    cursor.execute(
        f"GRANT {GRANT_PRIVILEGES} ON `{db_name}`.* TO %s@'localhost'",
        (db_user,),
    )
    cursor.execute("FLUSH PRIVILEGES")

    root_conn.commit()
    cursor.close()


def _assert_safe_identifier(name, label):
    """Database/table names can't be passed as bound parameters, so
    this rejects anything that isn't plain alphanumerics/underscore
    before it's ever interpolated into a query string. Not meant to
    validate config for correctness generally -- just to make sure a
    stray character in imps_config.toml can't change what SQL runs."""
    if not name or not all(c.isalnum() or c == "_" for c in name):
        sys.exit(
            f"Refusing to continue: the {label} {name!r} in imps_config.toml "
            "contains characters other than letters, numbers, and "
            "underscores. Fix it in imps_config.toml and re-run."
        )


def main():
    db_host, db_name, db_user, db_password = _load_target_config()

    print("IMPS database setup")
    print("====================")
    print(f"Target database : {db_name}")
    print(f"Target DB user  : {db_user}@localhost")
    print(f"DB host         : {db_host}")
    print("(These come from imps_config.toml -- edit that file, not this "
          "script, if any of them are wrong.)\n")

    root_conn = _connect_as_root(db_host)

    try:
        _provision(root_conn, db_host, db_name, db_user, db_password)
    except mysql.connector.Error as e:
        sys.exit(f"Database setup failed: {e}")
    finally:
        root_conn.close()

    print(
        "\nDone. The database and user account are ready.\n"
        "Next: start IMPS and finish setup in the browser at /setup -- "
        "that step creates IMPS's actual tables."
    )


if __name__ == "__main__":
    main()
