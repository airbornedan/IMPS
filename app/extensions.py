########################################################################
### SHARED CONFIG, DB POOL, AND HELPERS
########################################################################
# Central module for config, the DB connection pool, and shared helpers,
# imported by every blueprint.

import os
import logging
import threading
import time
import sys
import stat
import secrets
import bcrypt
import toml
from contextlib import contextmanager
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
    with open(CONFIG_PATH, mode="r") as f:
        imps_config = toml.load(f)
except Exception:
    os.system("clear")
    print(
        "IMPS CONFIGURATION ERROR -- IMPS cannot open the \
             imps_config.toml file which is required. Check that"
    )
    print(
        "this file is in the same directory as imps.py and \
             has the correct ownership and permissions."
    )
    sys.exit()

### DATABASE SETTINGS
dbhost = imps_config["database"]["host"]
dbname = imps_config["database"]["name"]
dbuser = imps_config["database"]["user"]
dbpass = imps_config["database"]["password"]

### DIRECTORY / NETWORK SETTINGS
IMPS_DIR = imps_config["directories"]["imps_dir"]
IMPS_IP = imps_config["directories"]["imps_ip"]

### ITEM_IMAGE_DIR HAS TWO DIFFERENT JOBS, SO IT NEEDS TWO DIFFERENT
### FORMS. The toml value (e.g. "static/images/items/") is a plain
### path relative to IMPS_DIR, same convention as backup_dir below.
### Templates use it directly as a URL fragment
### (<img src="{{ITEM_IMAGE_DIR}}{{item_pic}}">), which needs a
### leading slash to be a valid root-relative URL; filesystem code
### (os.listdir, os.remove, saving uploads, etc) needs an actual path
### on disk, anchored to IMPS_DIR -- and os.path.join() can't be used
### for that directly, because a component starting with "/" makes it
### treat that component as absolute and silently discard everything
### before it (IMPS_DIR would just vanish). So both forms are derived
### once, here, from the single relative config value:
###   ITEM_IMAGE_DIR    -- "/" + relative value, URL-relative, template-facing
###   ITEM_IMAGE_FS_DIR -- filesystem-absolute, resolved once here,
###                        for every filesystem call site instead
_item_image_dir_rel = imps_config["directories"]["item_image_dir"]
ITEM_IMAGE_DIR = "/" + _item_image_dir_rel
ITEM_IMAGE_FS_DIR = os.path.join(IMPS_DIR, _item_image_dir_rel)

### BACKUP_DIR HAS ONLY ONE JOB (FILESYSTEM), SO IT'S FULLY RESOLVED
### HERE, ANCHORED TO IMPS_DIR, REGARDLESS OF THE PROCESS'S CURRENT
### WORKING DIRECTORY.
BACKUP_DIR = os.path.join(IMPS_DIR, imps_config["directories"]["backup_dir"])

### VALIDATE imps_dir BEFORE ANYTHING ELSE TRIES TO USE IT
### A missing/incorrect imps_dir fails here with a plain, specific
### message and a clean exit. (BACKUP_DIR/ITEM_IMAGE_FS_DIR aren't
### checked here: they're allowed to not exist yet on a fresh install --
### the setup wizard's status page just shows them red.)
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
### OPTIONAL LAN-ONLY ACCESS RESTRICTION
########################################################################
# Off by default. If enabled ([access] restrict_to_lan = true in
# imps_config.toml, with lan_ip set), every request is checked against
# the derived home-network range and rejected if it's from outside it.
# See app/__init__.py's check_lan_restriction() for the actual
# enforcement -- this is just the config parsing, kept here alongside
# every other imps_config.toml-derived setting.
#
# NOT meant to handle VPNs, multiple subnets, reverse proxies, or
# Docker (see the comments in imps_config.toml.example) -- deliberately
# simple: one IP in, one assumed /24 (or an explicit /prefix) out.
import ipaddress


def _parse_lan_network(lan_ip):
    """Turn a config lan_ip value into an ipaddress network, or None.

    Plain IP ("192.168.0.42") assumes a standard home-router /24
    around it. An IP with an explicit prefix ("192.168.0.42/16") uses
    that instead, for the rare non-default network. Returns None for
    anything blank or unparseable, which callers treat as "restriction
    can't be enforced" -- see reload_config()/module init below, which
    both force restrict_to_lan off in that case rather than silently
    allowing (or silently blocking) every request.
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

########################################################################
### FLASK SECRET KEY (GENERATED ONCE AT FIRST RUN, THEN PERSISTED)
########################################################################
# The key used to sign session cookies is generated once and stored in
# its own file outside of source control, alongside the rest of the
# install (IMPS_DIR). Every subsequent start reads the same file back
# in, so sessions survive restarts.

SECRET_KEY_FILE = os.path.join(IMPS_DIR, ".secret_key")


def _get_or_create_secret_key():
    # If a key file already exists, use it.
    if os.path.isfile(SECRET_KEY_FILE):
        with open(SECRET_KEY_FILE, "r") as f:
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
        try:
            os.chmod(SECRET_KEY_FILE, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    return key


FLASK_SECRET_KEY = _get_or_create_secret_key()

########################################################################
### CSRF PROTECTION
########################################################################
# Flask-WTF's CSRFProtect checks every state-changing request (POST/PUT/
# PATCH/DELETE) for a valid csrf_token, generated per-session and embedded
# as a hidden field in each form (see templates). It's instantiated here,
# uninitialized, and wired up with csrf.init_app(app) in app/__init__.py
# so blueprints/templates can all share the same instance.
csrf = CSRFProtect()

########################################################################
### RATE LIMITING
########################################################################
# Shared limiter instance, initialized against the app in app/__init__.py.
# Used primarily to throttle login attempts (see app/blueprints/auth.py),
# since IMPS has a single shared password with no account lockout.
#
# storage_uri controls where request counts are tracked. It's read from
# an optional [rate_limit] section in imps_config.toml so a deployment
# that runs IMPS across more than one worker process (multiple mod_wsgi
# processes, multiple gunicorn workers, etc) can point every worker at
# the same store -- e.g. storage_uri = "redis://127.0.0.1:6379" --
# instead of each process only ever seeing its own share of requests.
# With no [rate_limit] section (the default), it falls back to
# "memory://": counts are tracked in that process's own memory only,
# which is correct as long as IMPS is served from a single process
# (any number of threads within it share that memory), and resets
# whenever the process restarts.
RATE_LIMIT_STORAGE_URI = imps_config.get("rate_limit", {}).get("storage_uri", "memory://")
limiter = Limiter(key_func=get_remote_address, storage_uri=RATE_LIMIT_STORAGE_URI)

########################################################################
### LOGIN BACKOFF (EXPONENTIAL, PER SOURCE IP)
########################################################################
# The flat "10 per minute; 100 per day" limiter above (applied in
# app/blueprints/auth.py) caps sustained guessing but treats every
# attempt the same up until the cutoff. This adds a second, cheaper
# layer on top of it: each consecutive failure from the same IP
# doubles how long that IP has to wait before its next attempt is even
# checked against the password, up to a capped ceiling. A single typo
# costs nothing; a sustained guessing attempt gets slower and slower
# rather than being allowed to run at a flat rate right up until it
# hits the per-minute wall.
#
# In-memory, keyed by source IP -- same "single process" caveat as the
# rate limiter's default memory:// storage (see RATE_LIMIT_STORAGE_URI
# above): correct for IMPS's normal single-process deployment, and
# resets on restart. A lock guards it since WSGIDaemonProcess runs
# multiple threads (see the similar _pool_rebuild_lock above).
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
# app/blueprints/auth.py), so this fires as an early warning well
# before an attacker could exhaust that budget, while being well above
# anything a person mistyping their own password would ever hit.
#
# Logs once per IP per rolling 24h window the first time it crosses
# the threshold, not on every failure after that -- a sustained attempt
# already shows up clearly as a single WARNING plus however many
# per-attempt log lines get written elsewhere; repeating this same line
# hundreds more times wouldn't add information, just noise.
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
    count = 0
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
# A real logger instead of print() -- gives severity levels (so a
# CRITICAL pool failure is distinguishable from routine INFO at a
# glance/grep), timestamps, and consistent formatting. Still writes to
# stderr, same as the print() calls it replaces, so it lands in the
# existing imps_error.log with no deployment/config changes needed.
logger = logging.getLogger("imps.db")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)
    logger.propagate = False

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
    fresh install that hasn't run the setup wizard). If every attempt
    fails, the app still starts -- get_db_connection() below rebuilds
    the pool lazily on a later request once the database becomes
    reachable.
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

    pass


# Guards lazy pool-rebuild attempts below. A lock (not just the cooldown
# timestamp alone) matters because WSGIDaemonProcess runs multiple
# threads (threads=5, per the Apache config) -- without it, several
# concurrent requests arriving while the pool is down could each try to
# rebuild it at the same moment.
_pool_rebuild_lock = threading.Lock()
_last_pool_rebuild_attempt = 0.0
POOL_REBUILD_COOLDOWN_SECONDS = 30  # don't hammer MySQL every request while it's down


@contextmanager
def get_db_connection():
    global db_pool, _last_pool_rebuild_attempt

    # SELF-HEALING: if the pool is missing (failed at startup, or a
    # prior attempt failed), try to rebuild it here, lazily, on
    # whatever request happens to need it next. Rate-limited via the
    # cooldown + lock so a sustained database outage doesn't turn into
    # a rebuild attempt on every single request.
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
# Everything above this point reads imps_config.toml once, at import
# time, into module-level names (dbhost, dbuser, HASHED_IMPS_PASS,
# etc). The /setup wizard (app/blueprints/setup.py) uses the functions
# below to write new DB credentials or a new IMPS password and apply
# them to the running process, with no restart required.
#
# write_config_values() persists new values into imps_config.toml.
# reload_config() re-reads the file and updates the live globals
# (rebuilding db_pool, rehashing HASHED_IMPS_PASS) so the next request
# sees the change.
#
# toml.dump() re-serializes the whole file, so hand-written comments
# in imps_config.toml (like the ones in the shipped .example file)
# don't survive a write from here.


def read_config():
    """Fresh read of imps_config.toml from disk -- independent of the
    module-level globals above (dbhost, HASHED_IMPS_PASS, etc), which
    only ever hold what was true at the last import/reload_config()
    call, and in the password's case, a one-way hash that can't be
    read back at all.

    Used by the setup wizard to check the *current* value of a field
    (e.g. the IMPS password) before deciding whether to keep it
    unchanged when someone leaves that field blank in a form -- see
    setup_password() in app/blueprints/setup.py.
    """
    with open(CONFIG_PATH, mode="r") as f:
        return toml.load(f)


def write_config_values(section, values):
    """Merge `values` into imps_config[section] and persist to disk.

    Does NOT apply the change to this process -- call reload_config()
    afterward for that. Kept as two steps so a caller can write, then
    decide whether/when to reload (e.g. only after the values have
    been validated).
    """
    with open(CONFIG_PATH, mode="r") as f:
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

    with open(CONFIG_PATH, mode="r") as f:
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
### SINGLE-QUERY HELPER
########################################################################
# For the common case of "one query, one connection, done" -- collapses
# the usual four lines (cursor = mydb.cursor() / execute / fetch /
# close(), all inside a `with get_db_connection()` block) into one call.
#
# NOT for multi-statement work: if a route runs more than one query
# against the same connection (a transaction, or a follow-up query that
# depends on the first -- e.g. LAST_INSERT_ID() right after an INSERT),
# keep using `with get_db_connection() as mydb:` directly instead. Each
# call to run_query() checks out its own connection from the pool, so
# splitting a multi-statement sequence across several run_query() calls
# would silently turn one logical unit of work into several separate
# pool checkouts -- slower, and no longer guaranteed to run on the same
# underlying MySQL connection/session.


def run_query(query, params=None, fetch="all"):
    """Run a single SQL statement on a connection borrowed from the pool.

    fetch="all" (default) -> cursor.fetchall()
    fetch="one"           -> cursor.fetchone()
    fetch=None            -> no fetch (INSERT/UPDATE/DELETE with nothing
                              to read back); returns None
    """
    with get_db_connection() as mydb:
        cursor = mydb.cursor()
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
### LIST-VIEW PAGE SIZE
########################################################################
# Shared by every paginated list route (inventory, itembycategory,
# search_result). This is a per-visitor preference, not a fixed value:
# since IMPS has no per-user account system (see HASHED_IMPS_PASS
# above -- a single shared password), it's stored the same way as the
# column-visibility settings on Control Panel > View -- a long-lived
# cookie set client-side by that page's JS. A browser with no cookie
# set falls back to DEFAULT_ITEMS_PER_PAGE via get_items_per_page()
# below.
DEFAULT_ITEMS_PER_PAGE = 25
ALLOWED_ITEMS_PER_PAGE = (25, 50, 100)


def get_items_per_page():
    """Return the caller's preferred list page size.

    Reads the items_per_page cookie (set from Control Panel > View);
    falls back to DEFAULT_ITEMS_PER_PAGE if the cookie is missing, not
    an integer, or holds a value outside ALLOWED_ITEMS_PER_PAGE -- the
    cookie is client-supplied, so treat it as untrusted input rather
    than trusting it straight into a SQL LIMIT.
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
# the int(page_req) parsing that used to be duplicated in
# main.search_result(), inventory.inventory(), and
# items.itembycategory() -- each of which called bare int() on it and
# relied on the surrounding @db_errors decorator to catch the
# resulting ValueError as if it were a database failure. This raises
# a specific, catchable error instead, so each route can show an
# accurate "that page doesn't exist" message rather than a misleading
# "database error".


class InvalidPageError(Exception):
    """Raised when a ?page= value isn't a valid positive integer."""

    pass


def get_offset_for_page(limit):
    """Return the SQL OFFSET for the current request's ?page= value.

    Reads request.args.get("page") directly (same as every call site
    used to), so no page argument means page 1 / offset 0. Raises
    InvalidPageError for anything that isn't a positive integer --
    callers should catch this and show a clear, specific error message
    rather than letting it bubble up as a generic database error.
    """
    page_req = request.args.get("page")
    if page_req is None:
        return 0

    try:
        page_num = int(page_req)
    except (TypeError, ValueError):
        raise InvalidPageError(f"{page_req!r} is not a valid page number.")

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
# the items.item_name column's actual varchar(256) limit, so a name
# over 50 is rejected here with a clear message rather than being
# silently truncated (or erroring at the DB layer) at 256.
MAX_ITEM_NAME_LENGTH = 50

# Box numbers: capped at a 4-digit ceiling. Plenty for a home inventory
# (a box number is looked up by its printed label, so it's meant to
# stay short and readable), and keeps box numbers visually distinct
# from item numbers, which can run much higher.
# Category names: same 50-character cap as item names, for the same
# reason (keeps category chips/lists readable; categories are meant to
# be short labels, not descriptions).
MAX_CATEGORY_NAME_LENGTH = 50

MAX_BOX_NUM = 9999


########################################################################
### UPLOAD SETTINGS
########################################################################

UPLOAD_FOLDER = ITEM_IMAGE_DIR
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

# Cap on the total size of the item-image directory. Since IMPS write
# access is deliberately open (public demo password), there's no other
# limit on how much a visitor could upload between resets -- this stops
# a script from filling the disk. Checked in items.py before each save.
MAX_IMAGE_DIR_BYTES = 500 * 1024 * 1024  # 500 MB


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def image_dir_size_bytes(image_dir_path):
    """Total size in bytes of everything currently in the item-image dir."""
    total = 0
    try:
        with os.scandir(image_dir_path) as entries:
            for entry in entries:
                if entry.is_file():
                    try:
                        total += entry.stat().st_size
                    except OSError:
                        pass
    except OSError:
        pass
    return total


def verify_and_reencode_image(save_path):
    """Confirm the uploaded file is actually a decodable image (not just
    named like one) and re-encode it, discarding the original bytes.

    This is the real defense against a malicious/polyglot file disguised
    with an image extension: allowed_file() only checks the filename, so
    this is the point where file *content* is verified. Returns True on
    success; on failure the bad file is removed and False is returned.
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
        try:
            os.remove(save_path)
        except OSError:
            pass
        return False


########################################################################
### SAFE ITEM-IMAGE FILENAME HELPER
########################################################################
# Turns a stored photo filename into a real filesystem path for
# deletion (e.g. replacing/removing an item's photo). The filename
# often round-trips through a hidden form field, so it's treated as
# untrusted input: a value like "../../../../etc/passwd" must never
# reach os.remove() directly. Used by any route that needs to resolve
# an image filename to a path, including cp_photofilesdel() in
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
# NOTE: redirects to the "auth" blueprint's login endpoint, since login()
# now lives in app/blueprints/auth.py instead of the top-level app.

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("loggedin"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)

    return decorated_function
