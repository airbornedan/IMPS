########################################################################
### SHARED CONFIG, DB POOL, AND HELPERS
########################################################################
# Central module for config, the DB connection pool, and shared helpers,
# imported by every blueprint.

import os
import re
import logging
import threading
import time
import sys
import stat
import secrets
import ipaddress
import bcrypt
import toml
from contextlib import contextmanager, suppress
from datetime import date
from functools import wraps
from flask import session, redirect, url_for, render_template, request
from mysql.connector import pooling
from mysql.connector.errors import IntegrityError
from flask_wtf import CSRFProtect
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

########################################################################
### LOAD CONFIGURATION FROM TOML FILE
########################################################################

CONFIG_PATH = "imps_config.toml"

try:
    with open(CONFIG_PATH) as f:
        imps_config = toml.load(f)
except Exception:
    os.system("clear")
    print(
        "IMPS CONFIGURATION ERROR -- IMPS cannot open the "
        "imps_config.toml file which is required. Check that"
    )
    print(
        "this file is in the same directory as imps.py and "
        "has the correct ownership and permissions."
    )
    sys.exit(1)

### DATABASE SETTINGS
dbhost = imps_config["database"]["host"]
dbname = imps_config["database"]["name"]
dbuser = imps_config["database"]["user"]
dbpass = imps_config["database"]["password"]

### DIRECTORY / NETWORK SETTINGS
IMPS_DIR = imps_config["directories"]["imps_dir"]
IMPS_IP = imps_config["directories"]["imps_ip"]

### INSTANCE LABEL -- optional, shown next to "IMPS" in the page header
### and browser tab title (see inject_instance_label() in app/__init__.py)
### so it's obvious at a glance which install this is when more than one
### is running. Blank/omitted shows nothing. Not part of the setup
### wizard -- toml-only, same as [access]/[rate_limit] below.
INSTANCE_LABEL = imps_config.get("instance", {}).get("label", "")

### ITEM_IMAGE_DIR HAS TWO JOBS, SO IT NEEDS TWO FORMS. The toml value
### (e.g. "static/images/items/") is a plain path relative to
### IMPS_DIR, same convention as backup_dir below. Templates use it as
### a URL fragment (<img src="{{ITEM_IMAGE_DIR}}{{item_pic}}">), which
### needs a leading slash to be root-relative. Filesystem code
### (os.listdir, os.remove, saving uploads) needs an actual path on
### disk anchored to IMPS_DIR -- os.path.join() can't do that directly,
### since a component starting with "/" makes it discard everything
### before it (IMPS_DIR would vanish). Both forms are derived once,
### here, from the single relative config value:
###   ITEM_IMAGE_DIR    -- "/" + relative value, URL-relative, template-facing
###   ITEM_IMAGE_FS_DIR -- filesystem-absolute, resolved once here
_item_image_dir_rel = imps_config["directories"]["item_image_dir"]
ITEM_IMAGE_DIR = "/" + _item_image_dir_rel
ITEM_IMAGE_FS_DIR = os.path.join(IMPS_DIR, _item_image_dir_rel)

### BACKUP_DIR HAS ONLY ONE JOB (FILESYSTEM), SO IT'S FULLY RESOLVED
### HERE, ANCHORED TO IMPS_DIR, REGARDLESS OF THE PROCESS'S CURRENT
### WORKING DIRECTORY.
BACKUP_DIR = os.path.join(IMPS_DIR, imps_config["directories"]["backup_dir"])

### VALIDATE imps_dir BEFORE ANYTHING ELSE TRIES TO USE IT
### A missing/incorrect imps_dir fails here with a plain message and
### clean exit. (BACKUP_DIR/ITEM_IMAGE_FS_DIR aren't checked: they're
### allowed to not exist yet on a fresh install -- setup wizard's
### status page just shows them red.)
if not os.path.isdir(IMPS_DIR):
    print("=" * 70)
    print("IMPS CONFIGURATION ERROR")
    print("=" * 70)
    print(f"The [directories] imps_dir setting in {CONFIG_PATH} is set to:")
    print(f"    {IMPS_DIR!r}")
    print("but that directory doesn't exist on this server.")
    print()
    print("Edit imps_config.toml and set imps_dir to the actual directory")
    print("IMPS is installed in -- the same directory imps_config.toml")
    print("itself is in -- then run IMPS again.")
    print("=" * 70)
    sys.exit(1)

########################################################################
### FLASK SECRET KEY (GENERATED ONCE AT FIRST RUN, THEN PERSISTED)
########################################################################
# Key used to sign session cookies, generated once and stored in its
# own file outside source control, alongside the install (IMPS_DIR).
# Every start reads the same file back, so sessions survive restarts.

SECRET_KEY_FILE = os.path.join(IMPS_DIR, ".secret_key")


def _get_or_create_secret_key():
    # If a key file already exists, use it.
    if os.path.isfile(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE) as f:
            key = f.read().strip()
        if key:
            return key
        # Empty/corrupt file -- fall through and regenerate.

    # No usable key file: generate a new cryptographically random key
    # and persist it with restrictive permissions.
    key = secrets.token_hex(32)
    fd = os.open(SECRET_KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(key)
    finally:
        # Force 600 permissions in case the process umask altered the mode above.
        with suppress(OSError):
            os.chmod(SECRET_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
    return key


FLASK_SECRET_KEY = _get_or_create_secret_key()

########################################################################
### CSRF PROTECTION
########################################################################
# Flask-WTF's CSRFProtect checks every state-changing request (POST/PUT/
# PATCH/DELETE) for a valid csrf_token, generated per-session and
# embedded as a hidden field in each form (see templates). Instantiated
# here, uninitialized, wired up with csrf.init_app(app) in
# app/__init__.py so blueprints/templates share the same instance.
csrf = CSRFProtect()

########################################################################
### RATE LIMITING
########################################################################
# Shared limiter instance, initialized against the app in app/__init__.py.
# Throttles login attempts (see app/blueprints/auth.py) -- IMPS has a
# single shared password with no account lockout.
#
# storage_uri controls where request counts are tracked, read from an
# optional [rate_limit] section in imps_config.toml so a multi-worker
# deployment (multiple mod_wsgi/gunicorn processes) can point every
# worker at the same store, e.g. storage_uri = "redis://127.0.0.1:6379".
# With no [rate_limit] section, falls back to "memory://": counts
# tracked in that process's own memory, correct for a single process
# (threads within it share the memory), resets on restart.
RATE_LIMIT_STORAGE_URI = imps_config.get("rate_limit", {}).get("storage_uri", "memory://")
limiter = Limiter(key_func=get_remote_address, storage_uri=RATE_LIMIT_STORAGE_URI)

########################################################################
### LOGIN BACKOFF (EXPONENTIAL, PER SOURCE IP)
########################################################################
# The flat "10 per minute; 100 per day" limiter above (applied in
# app/blueprints/auth.py) caps sustained guessing but treats every
# attempt the same up until the cutoff. This adds a cheaper second
# layer: each consecutive failure from the same IP doubles the wait
# before its next attempt is even checked against the password, up to
# a capped ceiling. A single typo costs nothing; a sustained guessing
# attempt slows down instead of running at a flat rate to the wall.
#
# In-memory, keyed by source IP -- same single-process caveat as the
# rate limiter's default memory:// storage (see RATE_LIMIT_STORAGE_URI
# above), resets on restart. A lock guards it since WSGIDaemonProcess
# runs multiple threads (see the similar _pool_rebuild_lock above).
LOGIN_BACKOFF_BASE_SECONDS = 1        # delay after the 1st failure
LOGIN_BACKOFF_MAX_SECONDS = 30        # ceiling, however many failures in a row
_login_backoff_lock = threading.Lock()
_login_backoff_state = {}  # ip -> {"fail_count": int, "blocked_until": float}


def login_backoff_seconds_remaining(ip):
    """How many more seconds `ip` must wait before attemptlogin() will
    check its password again. 0 means it can proceed now."""
    with _login_backoff_lock:
        state = _login_backoff_state.get(ip)
        if not state:
            return 0
        remaining = state["blocked_until"] - time.time()
        return remaining if remaining > 0 else 0


def login_backoff_record_failure(ip):
    """Record a failed login attempt from `ip` and set/extend its
    backoff window. Doubles with each consecutive failure, capped at
    LOGIN_BACKOFF_MAX_SECONDS."""
    with _login_backoff_lock:
        state = _login_backoff_state.setdefault(ip, {"fail_count": 0, "blocked_until": 0.0})
        state["fail_count"] += 1
        delay = min(
            LOGIN_BACKOFF_BASE_SECONDS * (2 ** (state["fail_count"] - 1)),
            LOGIN_BACKOFF_MAX_SECONDS,
        )
        state["blocked_until"] = time.time() + delay


def login_backoff_record_success(ip):
    """Clear `ip`'s backoff state after a successful login."""
    with _login_backoff_lock:
        _login_backoff_state.pop(ip, None)

########################################################################
### SUSTAINED-FAILURE LOGGING (24-HOUR WINDOW, PER SOURCE IP)
########################################################################
# Separate from the backoff state above (which resets on any success,
# so it can't be used to notice a *sustained* attempt spread out with
# occasional pauses). This only ever logs -- it doesn't block or slow
# anything down -- so an admin scanning imps_error.log (or grepping/
# alerting on it) has something to notice. 20 in 24 hours is well
# under the flat rate limiter's 100/day hard cap (see `limiter` above/
# app/blueprints/auth.py): fires as an early warning well before an
# attacker exhausts that budget, well above anything a person
# mistyping their own password would hit.
#
# Logs once per IP per rolling 24h window, on first crossing the
# threshold, not on every failure after -- a sustained attempt already
# shows as one WARNING plus the per-attempt log lines elsewhere;
# repeating this line hundreds more times adds noise, not information.
LOGIN_FAILURE_LOG_THRESHOLD = 20
LOGIN_FAILURE_LOG_WINDOW_SECONDS = 24 * 60 * 60
_login_failure_log_lock = threading.Lock()
_login_failure_log_state = {}  # ip -> {"count": int, "window_start": float, "logged": bool}


def login_failure_note_for_logging(ip):
    """Record a failed login attempt from `ip` for the 24h sustained-
    failure log, and log a WARNING the first time this IP crosses
    LOGIN_FAILURE_LOG_THRESHOLD failures within the current window."""
    now = time.time()
    should_log = False
    with _login_failure_log_lock:
        state = _login_failure_log_state.get(ip)
        if state is None or (now - state["window_start"]) >= LOGIN_FAILURE_LOG_WINDOW_SECONDS:
            # No state yet, or the previous window has fully expired --
            # start a fresh 24h window for this IP.
            state = {"count": 0, "window_start": now, "logged": False}
            _login_failure_log_state[ip] = state

        state["count"] += 1
        count = state["count"]
        if count >= LOGIN_FAILURE_LOG_THRESHOLD and not state["logged"]:
            state["logged"] = True
            should_log = True

    if should_log:
        logger.warning(
            f"Sustained login failures from {ip}: {count} failed attempts "
            f"in the last 24 hours (threshold {LOGIN_FAILURE_LOG_THRESHOLD})."
        )

### APP PASSWORD (HASHED)
pass_to_hash = imps_config["password"]["password"]
_pass_bytes = pass_to_hash.encode("utf-8")
_salt = bcrypt.gensalt()
HASHED_IMPS_PASS = bcrypt.hashpw(_pass_bytes, _salt)

########################################################################
### LOGGING
########################################################################
# A real logger instead of print() -- severity levels (CRITICAL pool
# failure distinguishable from routine INFO at a glance/grep),
# timestamps, consistent formatting. Still writes to stderr, so it
# lands in the existing imps_error.log with no config changes needed.
logger = logging.getLogger("imps.db")
logger.setLevel(logging.INFO)

########################################################################
### OPTIONAL LAN-ONLY ACCESS RESTRICTION
########################################################################
# Off by default. If enabled ([access] restrict_to_lan = true in
# imps_config.toml, with lan_ip set), every request is checked against
# the derived home-network range and rejected if from outside it. See
# app/__init__.py's check_lan_restriction() for the enforcement --
# this is just the config parsing, kept alongside every other
# imps_config.toml-derived setting.
#
# Not meant to handle VPNs, multiple subnets, reverse proxies, or
# Docker (see imps_config.toml.example) -- deliberately simple: one IP
# in, one assumed /24 (or explicit /prefix) out.


def _parse_lan_network(lan_ip):
    """Turn a config lan_ip value into an ipaddress network, or None.

    Plain IP ("192.168.0.42") assumes a standard home-router /24
    around it. An IP with an explicit prefix ("192.168.0.42/16") uses
    that instead, for non-default networks. Returns None for anything
    blank or unparseable; callers treat that as "restriction can't be
    enforced" -- see reload_config()/module init below, which both
    force restrict_to_lan off in that case rather than silently
    allowing (or blocking) every request.
    """
    if not lan_ip:
        return None
    try:
        if "/" not in lan_ip:
            lan_ip = f"{lan_ip}/24"
        return ipaddress.ip_interface(lan_ip).network
    except ValueError:
        return None


def _load_lan_restriction(config):
    access_cfg = config.get("access", {})
    restrict_requested = bool(access_cfg.get("restrict_to_lan", False))
    lan_network = _parse_lan_network(access_cfg.get("lan_ip", ""))

    if restrict_requested and lan_network is None:
        logger.error(
            "[access] restrict_to_lan is true but lan_ip is missing/invalid "
            "in imps_config.toml -- LAN restriction is DISABLED until this "
            "is fixed, rather than blocking (or failing to block) every "
            "request based on a value that couldn't be parsed."
        )

    enabled = restrict_requested and lan_network is not None
    return enabled, lan_network


LAN_RESTRICTION_ENABLED, LAN_NETWORK = _load_lan_restriction(imps_config)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

########################################################################
### MAINTENANCE MODE
########################################################################
# File-based, not in-memory -- WSGI runs 2 processes with no shared
# memory. Enforcement is block_during_maintenance() in app/__init__.py.

MAINTENANCE_LOCK_FILE = os.path.join(IMPS_DIR, "maintenance.lock")


def maintenance_mode_active():
    return os.path.isfile(MAINTENANCE_LOCK_FILE)


def enter_maintenance_mode(reason=""):
    with open(MAINTENANCE_LOCK_FILE, "w") as f:
        f.write(f"{date.today()} {reason}\n")


def exit_maintenance_mode():
    with suppress(FileNotFoundError):
        os.remove(MAINTENANCE_LOCK_FILE)


########################################################################
### SQL CONNECTION POOL
########################################################################
# A pool of reusable connections, safe to share across Flask's worker
# threads and immune to the timeout issues a single long-lived
# connection would have.


def _build_pool():
    return pooling.MySQLConnectionPool(
        pool_name="imps_pool",
        pool_size=5,                 # up to 5 connections kept ready
        pool_reset_session=True,     # resets session variables on reuse
        host=dbhost,
        database=dbname,
        user=dbuser,
        password=dbpass,
        autocommit=True,
        connection_timeout=5,        # bounds worst-case latency for an
                                      # unreachable host
    )


def _build_pool_with_retry(max_attempts=2, base_delay_seconds=1):
    """Used only once, at module import (app/worker startup).

    Makes a small, bounded number of attempts to build the pool so
    startup stays fast even with no database reachable yet (e.g. a
    fresh install, setup wizard not run). If every attempt fails, the
    app still starts -- get_db_connection() below rebuilds the pool
    lazily on a later request once the database is reachable.
    """
    delay = base_delay_seconds
    for attempt in range(1, max_attempts + 1):
        try:
            pool = _build_pool()
            logger.info(f"Connection pool initialized (attempt {attempt}/{max_attempts}).")
            return pool
        except Exception as e:
            logger.error(f"Pool init attempt {attempt}/{max_attempts} failed: {e}")
            if attempt < max_attempts:
                time.sleep(delay)
                delay *= 2

    logger.warning(
        "Connection pool could NOT be initialized at startup -- db_pool "
        "is None. The app will still start and serve pages normally "
        "(e.g. the setup wizard or /welcome's status page), and will "
        "keep attempting to rebuild the pool lazily on incoming "
        "requests (see get_db_connection below) once the database "
        "becomes reachable -- no restart needed."
    )
    return None


db_pool = _build_pool_with_retry()

########################################################################
### POOLED CONNECTION CONTEXT MANAGER
########################################################################
# Every route acquires a connection with:
#     try:
#         with get_db_connection() as mydb:
#             ...queries...
#     except DBConnectionError as e:
#         ...could not connect...
#     except Exception as e:
#         ...query/processing failure...
# The connection is guaranteed to be returned to the pool when the
# `with` block exits, whether it exits normally, via `return`, or via
# an exception.


class DBConnectionError(Exception):
    """Raised when a connection cannot be obtained or verified from the pool."""


# Guards lazy pool-rebuild attempts below. A lock (not just the
# cooldown timestamp) matters because WSGIDaemonProcess runs multiple
# threads (threads=5, per the Apache config) -- without it, concurrent
# requests arriving while the pool is down could each try to rebuild
# it at once.
_pool_rebuild_lock = threading.Lock()
_last_pool_rebuild_attempt = 0.0
POOL_REBUILD_COOLDOWN_SECONDS = 30  # don't hammer MySQL every request while it's down


@contextmanager
def get_db_connection():
    global db_pool, _last_pool_rebuild_attempt

    # SELF-HEALING: if the pool is missing (failed at startup, or a
    # prior attempt failed), try rebuilding it here, lazily, on
    # whatever request needs it next. Rate-limited via the cooldown +
    # lock so a sustained outage doesn't trigger a rebuild attempt on
    # every request.
    if db_pool is None:
        with _pool_rebuild_lock:
            now = time.time()
            if db_pool is None and (now - _last_pool_rebuild_attempt) >= POOL_REBUILD_COOLDOWN_SECONDS:
                _last_pool_rebuild_attempt = now
                logger.warning("db_pool is None -- attempting a lazy rebuild.")
                try:
                    db_pool = _build_pool()
                    logger.info("Connection pool rebuilt successfully -- database access restored.")
                except Exception as e:
                    logger.error(f"Lazy pool rebuild attempt failed, still down: {e}")

    if db_pool is None:
        raise DBConnectionError("Database connection pool is not available.")

    try:
        mydb = db_pool.get_connection()
        mydb.ping(reconnect=True)
    except Exception as e:
        logger.error(f"Failed to obtain a connection from the pool: {e}")
        raise DBConnectionError(str(e)) from e

    try:
        yield mydb
    finally:
        # CRITICAL: Always return the socket back to the pool to prevent long-term timeout drops
        mydb.close()


########################################################################
### CONFIG WRITE / RELOAD (used by the setup wizard)
########################################################################
# Everything above reads imps_config.toml once, at import time, into
# module-level names (dbhost, dbuser, HASHED_IMPS_PASS, etc). The
# /setup wizard (app/blueprints/setup.py) uses the functions below to
# write new DB credentials or app password and apply them to the
# running process, no restart required.
#
# write_config_values() persists new values into imps_config.toml.
# reload_config() re-reads the file and updates the live globals
# (rebuilding db_pool, rehashing HASHED_IMPS_PASS) so the next request
# sees the change.
#
# toml.dump() re-serializes the whole file, so hand-written comments
# in imps_config.toml (like the shipped .example file) don't survive a
# write from here.


def read_config():
    """Fresh read of imps_config.toml from disk -- independent of the
    module-level globals above (dbhost, HASHED_IMPS_PASS, etc), which
    only hold what was true at the last import/reload_config() call,
    and in the password's case, a one-way hash that can't be read back.

    Used by the setup wizard to check the *current* value of a field
    (e.g. the IMPS password) before deciding whether to keep it
    unchanged when someone leaves that field blank -- see
    setup_password() in app/blueprints/setup.py.
    """
    with open(CONFIG_PATH) as f:
        return toml.load(f)


def write_config_values(section, values):
    """Merge `values` into imps_config[section] and persist to disk.

    Does NOT apply the change to this process -- call reload_config()
    afterward for that. Kept as two steps so a caller can write, then
    decide whether/when to reload (e.g. only after the values have
    been validated).
    """
    with open(CONFIG_PATH) as f:
        on_disk = toml.load(f)

    on_disk.setdefault(section, {})
    on_disk[section].update(values)

    with open(CONFIG_PATH, mode="w") as f:
        toml.dump(on_disk, f)


def reload_config():
    """Re-read imps_config.toml and apply it to the running process:
    rebuilds db_pool against the (possibly new) database settings and
    rehashes HASHED_IMPS_PASS against the (possibly new) app password.

    Safe to call even if the new DB settings are still wrong -- pool
    rebuild failures are caught and surfaced via db_pool staying None,
    exactly like the lazy-rebuild path in get_db_connection() above,
    rather than raised here.
    """
    global imps_config, dbhost, dbname, dbuser, dbpass, db_pool, HASHED_IMPS_PASS
    global LAN_RESTRICTION_ENABLED, LAN_NETWORK

    with open(CONFIG_PATH) as f:
        imps_config = toml.load(f)

    dbhost = imps_config["database"]["host"]
    dbname = imps_config["database"]["name"]
    dbuser = imps_config["database"]["user"]
    dbpass = imps_config["database"]["password"]

    LAN_RESTRICTION_ENABLED, LAN_NETWORK = _load_lan_restriction(imps_config)

    try:
        db_pool = _build_pool()
        logger.info("Config reload: connection pool rebuilt.")
    except Exception as e:
        db_pool = None
        logger.error(f"Config reload: connection pool rebuild failed: {e}")

    new_pass = imps_config["password"]["password"]
    HASHED_IMPS_PASS = bcrypt.hashpw(new_pass.encode("utf-8"), bcrypt.gensalt())


########################################################################
### DB ERROR-HANDLING DECORATOR
########################################################################
# Wraps a route so it doesn't need its own
# "try: with get_db_connection() ... except DBConnectionError ...
# except Exception ..." boilerplate. Each route supplies its own
# user-facing error wording as decorator arguments.
#
# Usage:
#   @bp.route("/boxadd")
#   @login_required
#   @db_errors(exec_msg="Database error when parsing layout values.")
#   def boxadd():
#       with get_db_connection() as mydb:
#           ...
#
# Pass integrity_msg= as well for routes that can hit a duplicate-key/
# unique-constraint violation (e.g. renaming a category to a name that
# already exists) and want a friendlier message than the generic
# execution-error one.


def db_errors(conn_msg=None, exec_msg=None, integrity_msg=None, err_page_from="/"):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except DBConnectionError as e:
                logger.error(f"Pool connection error in {f.__name__}: {e}")
                return render_template(
                    "errorpage.html",
                    err_message=conn_msg or "Database error. Could not connect.",
                    err_page_from=err_page_from,
                )
            except IntegrityError as e:
                logger.error(f"Integrity error in {f.__name__}: {e}")
                return render_template(
                    "errorpage.html",
                    err_message=integrity_msg or "Database error. That value already exists.",
                    err_page_from=err_page_from,
                )
            except Exception as e:
                logger.error(f"Database execution error in {f.__name__}: {e}")
                return render_template(
                    "errorpage.html",
                    err_message=exec_msg or "Database error.",
                    err_page_from=err_page_from,
                )

        return wrapped

    return decorator


########################################################################
### URL ROUTE INT VALIDATION
########################################################################
# Converts named URL route arguments to int, or returns errorpage.html
# for a non-numeric value. Runs after Flask has already matched the
# route, so it replaces the try/except int() block that would
# otherwise open every view function taking a numeric route segment.
#
# Usage:
#   @bp.route("/itemdetail/<item_num>")
#   @login_required
#   @validate_int("item_num")
#   def itemdetail(item_num):
#       # item_num is already an int here
#       ...


def validate_int(*names, err_message="Entry is not a number.", err_page_from="/"):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            for name in names:
                try:
                    kwargs[name] = int(kwargs[name])
                except (KeyError, ValueError):
                    return render_template(
                        "errorpage.html",
                        err_message=err_message,
                        err_page_from=err_page_from,
                    )
            return f(*args, **kwargs)

        return wrapped

    return decorator


########################################################################
### FORM FIELD INT VALIDATION
########################################################################
# Converts a submitted form value to int, or returns (None, response)
# with response already set to errorpage.html. Callers unpack both and
# return early on a non-None response:
#
#   box_to_del, err = parse_int(request.form.get("box_to_del", ""))
#   if err:
#       return err


def parse_int(value, err_message="Entry is not a number.", err_page_from="/"):
    try:
        return int(value), None
    except ValueError:
        return None, render_template(
            "errorpage.html",
            err_message=err_message,
            err_page_from=err_page_from,
        )


########################################################################
### SINGLE-QUERY HELPER
########################################################################
# For the common case of "one query, one connection, done" -- collapses
# the usual four lines (cursor = mydb.cursor() / execute / fetch /
# close(), all inside a `with get_db_connection()` block) into one call.
#
# NOT for multi-statement work: if a route runs more than one query on
# the same connection (a transaction, or a follow-up query depending
# on the first, e.g. LAST_INSERT_ID() after an INSERT), use
# `with get_db_connection() as mydb:` directly instead. Each
# run_query() call checks out its own connection from the pool, so
# splitting a multi-statement sequence across several calls turns one
# logical unit of work into several separate pool checkouts -- slower,
# and not guaranteed to run on the same MySQL connection/session.


def run_query(query, params=None, fetch="all", as_dict=False):
    """Run a single SQL statement on a connection borrowed from the pool.

    fetch="all" (default) -> cursor.fetchall()
    fetch="one"           -> cursor.fetchone()
    fetch=None            -> no fetch (INSERT/UPDATE/DELETE with nothing
                              to read back); returns None

    as_dict=False (default) -> rows come back as plain tuples,
                                positional access (result[0], ...).
                                Every existing call site depends on it.
    as_dict=True            -> rows come back as dicts keyed by column
                                name/alias (result['col_name']), so
                                field access doesn't depend on SELECT
                                column order. Opt in per-call for
                                queries like ITEMS_WITH_CAT_NAME where
                                position isn't a reliable contract on
                                its own -- see items.py.
    """
    with get_db_connection() as mydb:
        cursor = mydb.cursor(dictionary=True) if as_dict else mydb.cursor()
        cursor.execute(query, params or ())
        if fetch == "all":
            result = cursor.fetchall()
        elif fetch == "one":
            result = cursor.fetchone()
        else:
            result = None
        cursor.close()
        return result


########################################################################
### CATEGORY / LOCATION NAME <-> NUMERIC FK RESOLUTION
########################################################################
# items.cat_num and boxes.loc_num are real foreign keys against
# categories.cat_num / locations.loc_num (see deploy/schema.sql), but
# forms (itemadd.html, itemedit.html, boxadd.html, boxedit.html) submit
# a category/location *name*, so every write path needs to resolve
# that name to its numeric id -- creating the row first if new.
#
# Relies on the cat_name/loc_name UNIQUE constraint (INSERT, catch
# IntegrityError) rather than SELECT-then-check-then-INSERT: the
# latter is a race condition, since two concurrent requests could both
# see "doesn't exist yet" before either INSERT lands, producing
# duplicate rows. Centralized here since both write paths and
# read-back-the-id paths need it.
def get_or_create_cat_num(cursor, cat_name):
    if not cat_name:
        cat_name = "Uncategorized"
    with suppress(IntegrityError):
        cursor.execute("INSERT INTO categories (cat_name) VALUES (%s)", (cat_name,))
    cursor.execute("SELECT cat_num FROM categories WHERE cat_name = %s", (cat_name,))
    row = cursor.fetchone()
    # Falls back to 0 (Uncategorized) only if something has gone
    # seriously wrong -- Uncategorized always exists (see cp_catdel in
    # control_panel.py).
    return row[0] if row else 0


def get_or_create_loc_num(cursor, loc_name):
    if not loc_name:
        loc_name = "Unspecified"
    with suppress(IntegrityError):
        cursor.execute("INSERT INTO locations (loc_name) VALUES (%s)", (loc_name,))
    cursor.execute("SELECT loc_num FROM locations WHERE loc_name = %s", (loc_name,))
    row = cursor.fetchone()
    # Same reasoning as get_or_create_cat_num() above -- Unspecified
    # is guaranteed to exist and never be deleted (see cp_delloc).
    return row[0] if row else 0


########################################################################
### boxes.box_last_changed -- MARKING A BOX AS "TOUCHED"
########################################################################
# Tracks physical/contents changes, not every edit: item added, moved,
# or deleted counts; box name/location edited counts; editing an
# item's name/description/category/photo/date in place does NOT. Call
# sites: iteminsert()/itemdeleted()/itemupdate() in items.py;
# boxmoveitemssuccess() in boxes.py.
#
# No-ops on a falsy/None box_num (an orphaned item has no box to
# touch) rather than gating each call site with its own if-check.
def touch_box_last_changed(cursor, box_num):
    if not box_num:
        return
    cursor.execute(
        "UPDATE boxes SET box_last_changed = %s WHERE box_num = %s",
        (str(date.today()), box_num),
    )


def get_available_boxes():
    result = run_query("SELECT box_num FROM boxes ORDER BY box_num")
    return [row[0] for row in result]


def get_available_cats():
    result = run_query("SELECT cat_name FROM categories ORDER BY cat_name")
    return [row[0] for row in result]


def get_available_locs():
    result = run_query("SELECT loc_name FROM locations ORDER BY loc_name")
    return [row[0] for row in result]


########################################################################
### ITEM PHOTOS -- cover photo (position 1, lowest photo_num) resolved
### as "item_pic" for any items query, so every existing read site
### (which already reads row['item_pic']) keeps working unchanged.
### Requires the items table aliased as `i` in the query this is
### spliced into -- true of every items query in the app.
########################################################################
ITEM_COVER_PHOTO_SELECT = "COALESCE(cover.filename, 'none.jpg') AS item_pic"
ITEM_COVER_PHOTO_JOIN = """
    LEFT JOIN item_photos cover ON cover.photo_num = (
        SELECT MIN(ip.photo_num) FROM item_photos ip WHERE ip.item_num = i.item_num
    )
"""


def get_item_photos(item_num):
    """Every photo for an item, position 1 (cover) first."""
    return run_query(
        "SELECT photo_num, filename FROM item_photos WHERE item_num = %s ORDER BY photo_num",
        (item_num,),
    )


########################################################################
### LIST-VIEW PAGE SIZE
########################################################################
# Shared by every paginated list route (inventory, itemsbycategory,
# search_result). A per-visitor preference, not a fixed value: IMPS
# has no per-user account system (see HASHED_IMPS_PASS above -- a
# single shared password), so it's stored the same way as the
# column-visibility settings on Control Panel > View -- a long-lived
# cookie set client-side by that page's JS. No cookie falls back to
# DEFAULT_ITEMS_PER_PAGE via get_items_per_page() below.
DEFAULT_ITEMS_PER_PAGE = 25
ALLOWED_ITEMS_PER_PAGE = (25, 50, 100)


def get_items_per_page():
    """Return the caller's preferred list page size.

    Reads the items_per_page cookie (set from Control Panel > View);
    falls back to DEFAULT_ITEMS_PER_PAGE if missing, not an integer, or
    outside ALLOWED_ITEMS_PER_PAGE -- the cookie is client-supplied, so
    treat it as untrusted input rather than trusting it into a SQL LIMIT.
    """
    raw = request.cookies.get("items_per_page")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_ITEMS_PER_PAGE
    return value if value in ALLOWED_ITEMS_PER_PAGE else DEFAULT_ITEMS_PER_PAGE


########################################################################
### PAGE-PARAMETER HELPER (SHARED BY EVERY PAGINATED LIST ROUTE)
########################################################################
# ?page= is client-supplied (typed in the URL, bookmarked, or shared),
# so it can't be trusted to be a valid positive integer. Centralizes
# int(page_req) parsing for main.search_result(), inventory.inventory(),
# and items.itemsbycategory(). Raises a specific, catchable error
# instead of a bare ValueError, so each route can show an accurate
# "that page doesn't exist" message rather than a misleading
# "database error".


class InvalidPageError(Exception):
    """Raised when a ?page= value isn't a valid positive integer."""


def get_offset_for_page(limit):
    """Return the SQL OFFSET for the current request's ?page= value.

    Reads request.args.get("page") directly, so no page argument means
    page 1 / offset 0. Raises InvalidPageError for anything that isn't
    a positive integer -- callers should catch this and show a clear,
    specific error message rather than a generic database error.
    """
    page_req = request.args.get("page")
    if page_req is None:
        return 0

    try:
        page_num = int(page_req)
    except (TypeError, ValueError) as err:
        raise InvalidPageError(f"{page_req!r} is not a valid page number.") from err

    if page_num < 1:
        raise InvalidPageError(f"{page_req!r} is not a valid page number.")

    return limit * (page_num - 1)


########################################################################
### FIELD LIMITS (ENFORCED SERVER-SIDE -- THE UI ALSO ENFORCES THESE,
### VIA maxlength/JS IN THE TEMPLATES, BUT THAT'S CLIENT-SIDE ONLY AND
### CAN'T BE TRUSTED ON ITS OWN: A DIRECT POST BYPASSES IT ENTIRELY)
########################################################################
# Item names: capped at 50 so the item list/grid views stay readable --
# there's a separate item_desc field for anything longer. Well under
# items.item_name's actual varchar(256) limit, so a name over 50 is
# rejected here with a clear message rather than silently truncated
# (or erroring at the DB layer) at 256.
MAX_ITEM_NAME_LENGTH = 50

# Box numbers: capped at a 4-digit ceiling. Plenty for a home inventory
# (a box number is looked up by its printed label, so it stays short
# and readable), and keeps box numbers visually distinct from item
# numbers, which can run much higher.
# Category names: same-width cap as categories.cat_name varchar(64)
# (see deploy/schema.sql) -- keeps category chips/lists readable;
# categories are short labels, not descriptions.
MAX_CATEGORY_NAME_LENGTH = 64

# Location names: same-width cap as locations.loc_name varchar(255)
# (see deploy/schema.sql). Unlike item/category names, this matches
# the column exactly rather than leaving headroom below it -- there's
# no separate "long form" field for locations, so the cap here exists
# purely to reject an over-limit value with a clear message instead of
# a silent truncation or a raw DB error, not to keep the UI compact.
MAX_LOCATION_NAME_LENGTH = 255

# Box names: same-width cap as boxes.box_name varchar(64) (see
# deploy/schema.sql) -- keeps box list/label displays readable;
# boxes are short labels, not descriptions.
MAX_BOX_NAME_LENGTH = 64

# Item descriptions: same-width cap as items.item_desc varchar(255)
# (see deploy/schema.sql), for the same reason as MAX_LOCATION_NAME_LENGTH
# above -- this is the field with the most room already, so the cap
# here is the actual DB limit, not a UI-driven one.
MAX_ITEM_DESC_LENGTH = 255

MAX_BOX_NUM = 9999

# Photos per item: enforced here (server-side) and mirrored in the
# itemedit.html grid (6 slots). Not a DB constraint -- MySQL has no
# clean per-group row-count check.
MAX_ITEM_PHOTOS = 6


########################################################################
### UPLOAD SETTINGS
########################################################################

UPLOAD_FOLDER = ITEM_IMAGE_DIR
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

# Cap on the total size of the item-image directory. IMPS write access
# is deliberately open (public demo password), with no other limit on
# how much a visitor could upload between resets -- this stops a
# script from filling the disk. Checked in items.py before each save.
MAX_IMAGE_DIR_BYTES = 500 * 1024 * 1024  # 500 MB

# Serializes the MAX_IMAGE_DIR_BYTES check with the save that follows
# it in items.py, so concurrent uploads check and save atomically with
# respect to each other rather than racing past the cap together.
# In-memory, single-process scope -- same as _login_backoff_lock/
# _pool_rebuild_lock above: each worker process serializes its own
# uploads, not against other workers. A soft anti-fill-the-disk
# measure, not a hard guarantee.
IMAGE_UPLOAD_LOCK = threading.Lock()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def image_dir_size_bytes(image_dir_path):
    """Total size in bytes of everything currently in the item-image dir."""
    total = 0
    try:
        with os.scandir(image_dir_path) as entries:
            for entry in entries:
                if entry.is_file():
                    with suppress(OSError):
                        total += entry.stat().st_size
    except OSError:
        pass
    return total


def verify_and_reencode_image(save_path):
    """Confirm the uploaded file is actually a decodable image (not just
    named like one) and re-encode it, discarding the original bytes.

    Real defense against a malicious/polyglot file disguised with an
    image extension: allowed_file() only checks the filename; this is
    where file *content* is verified. Returns True on success; on
    failure the bad file is removed and False is returned.
    """
    from PIL import Image, UnidentifiedImageError

    try:
        with Image.open(save_path) as img:
            img.verify()  # raises if the file isn't a valid image
        # verify() leaves the file object unusable for further ops, so
        # reopen fresh to actually process/re-save it.
        with Image.open(save_path) as img:
            img = img.convert("RGB") if img.mode not in ("RGB", "RGBA") else img
            img.save(save_path)  # re-encode: strips any non-pixel payload
        return True
    except (UnidentifiedImageError, OSError, ValueError):
        with suppress(OSError):
            os.remove(save_path)
        return False


########################################################################
### SAFE ITEM-IMAGE FILENAME HELPER
########################################################################
# Turns a stored photo filename into a real filesystem path for
# deletion (e.g. replacing/removing an item's photo). The filename
# often round-trips through a hidden form field, so treat it as
# untrusted input: a value like "../../../../etc/passwd" must never
# reach os.remove() directly. Used by any route resolving an image
# filename to a path, including cp_photofilesdel() in
# app/blueprints/control_panel.py.


def safe_image_path(filename, image_dir):
    """Return an absolute path for `filename` inside `image_dir` if (and
    only if) it's a plain filename with no directory components/traversal
    and actually resolves to a location inside image_dir. Returns None if
    the filename is missing, malformed, or would escape image_dir.
    """
    if not filename or filename in (".", ".."):
        return None
    # Must be a bare filename -- no "/", no "..", no leading path at all.
    if os.path.basename(filename) != filename:
        return None
    resolved = os.path.realpath(os.path.join(image_dir, filename))
    if os.path.dirname(resolved) != os.path.realpath(image_dir):
        return None
    return resolved


########################################################################
### SAFE "BACK TO" URL HELPER
########################################################################
# Used by routes that want to send the user back to whatever page they
# came from (e.g. after deleting an item). Never trust request.referrer
# or a form field directly as a redirect target -- that's an open
# redirect vector (e.g. back_url=https://evil.example/phish). Only a
# same-site, root-relative path is considered safe.

def safe_relative_url(url):
    if not url:
        return None
    # Must start with a single "/" (root-relative) -- "//host/path" is
    # browser-interpreted as protocol-relative to another host, and
    # anything with "://" is an absolute URL to somewhere else entirely.
    if not url.startswith("/") or url.startswith("//") or "://" in url:
        return None
    return url


########################################################################
### AUTH DECORATOR
########################################################################
# NOTE: redirects to the "auth" blueprint's login endpoint --
# login() lives in app/blueprints/auth.py.

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("loggedin"):
            return redirect(url_for("auth.login", next=request.full_path))
        return f(*args, **kwargs)

    return decorated_function


########################################################################
### ROUTE -> HELP TOPIC
########################################################################
# Converts a Flask route rule to a help topic name. Used by
# app/__init__.py's inject_help_topic() and app/dev_checks.py.
def route_to_help_topic(rule):
    rule = re.sub(r"<[^>]+>", "", rule)
    return rule.strip("/").replace("/", "_") or "home"
