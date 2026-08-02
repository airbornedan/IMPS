########################################################################
### SETUP BLUEPRINT — FIRST-RUN DATABASE / PASSWORD WIZARD
########################################################################
# Runs before app/blueprints/main.py's /welcome verification screen.
# /welcome only tests settings already in imps_config.toml; this
# blueprint gets a brand-new install to that point -- showing
# copy-pasteable Ubuntu/MariaDB install steps, taking DB credentials,
# testing the connection live, creating IMPS's tables, optionally
# loading sample data, and setting the IMPS password -- all without
# touching imps_config.toml by hand or restarting the server.
#
# No @login_required anywhere in this file: there is no usable
# password yet the first time any of this runs (imps_config.toml
# ships with only a placeholder), same as /welcome.
import os

from flask import Blueprint, request, render_template, redirect, url_for

from app import extensions
from app.extensions import (
    get_db_connection,
    DBConnectionError,
    read_config,
    IMPS_DIR,
    BACKUP_DIR,
    ITEM_IMAGE_FS_DIR,
    logger,
)

bp = Blueprint("setup", __name__)

SCHEMA_SQL_PATH = os.path.join("deploy", "schema.sql")


def _first_run_active():
    """Mirrors the check in main.home() -- this whole wizard should be
    unreachable once setup has been completed (first.run renamed away),
    so someone can't stumble back into /setup and rewrite a working
    install's credentials by guessing the URL."""
    return os.path.isfile(os.path.join(IMPS_DIR, "first.run"))


def _guard():
    """Returns a redirect if first.run is gone, else None. Call at the
    top of every route in this file (can't use a decorator+before_request
    cleanly here since a couple of routes need slightly different
    redirect targets -- this keeps it explicit and easy to scan)."""
    if not _first_run_active():
        return redirect(url_for("main.home"))
    return None


########################################################################
### LANDING PAGE: FULL STATUS (DB + DIRECTORIES), EACH ITS OWN TABLE
########################################################################
@bp.route("/setup")
def setup_landing():
    guard = _guard()
    if guard:
        return guard

    ########################################
    ### TEST DATABASE

    db_conn = False
    db_tables = False

    try:
        with get_db_connection() as mydb:
            db_conn = True
            cursor = mydb.cursor()
            ### CHECKS THAT THE EXPECTED TABLES EXIST -- NOT THAT THEY
            ### HAVE DATA IN THEM. A freshly-created, genuinely empty
            ### database (e.g. sample data was skipped) still shows
            ### green here.
            found = _existing_imps_tables(cursor, extensions.dbname)
            cursor.close()
            db_tables = found == EXPECTED_TABLES
    except DBConnectionError as e:
        logger.error(f"Database connection check failed: {e}")
        db_conn = False
    except Exception as e:
        logger.error(f"Database table check failed: {e}")
        db_tables = False

    ########################################
    ### TEST DIRECTORIES
    ### (imps_dir isn't checked here -- if it were wrong, the app
    ### wouldn't have booted at all, per the startup check in
    ### extensions.py, so reaching this page already proves it's fine.
    ### Showing a light for it here would be meaningless -- it'd always
    ### be green, or you'd never see this page to find out it wasn't.)

    item_image_dir_exists = os.path.exists(ITEM_IMAGE_FS_DIR)
    backup_dir_exists = os.path.exists(BACKUP_DIR)

    all_green = db_conn and db_tables and item_image_dir_exists and backup_dir_exists

    return render_template(
        "setup/setup_landing.html",
        db_conn=db_conn,
        db_tables=db_tables,
        item_image_dir_exists=item_image_dir_exists,
        backup_dir_exists=backup_dir_exists,
        all_green=all_green,
    )


########################################################################
### DIRECTORIES INFO (READ-ONLY REFERENCE -- IMPS_DIR ETC ARE SET IN
### imps_config.toml, NOT THROUGH THE WEB UI, SINCE A WRONG imps_dir
### IS WHAT MAKES THE APP FAIL TO EVEN IMPORT -- SEE extensions.py)
########################################################################
@bp.route("/setup/directories")
def setup_directories_info():
    guard = _guard()
    if guard:
        return guard
    return render_template("setup/setup_directories_info.html")


########################################################################
### MARIADB INSTALL INSTRUCTIONS (UBUNTU ONLY -- IMPS' ONLY SUPPORTED OS)
########################################################################
@bp.route("/setup/mariadb")
def setup_mariadb():
    guard = _guard()
    if guard:
        return guard
    return render_template("setup/setup_mariadb.html")


########################################################################
### DATABASE CREDENTIALS FORM + LIVE TEST + TABLE CREATION
########################################################################
EXPECTED_TABLES = {"boxes", "categories", "items", "locations", "backup_history"}


def _existing_imps_tables(cursor, schema_name):
    """Which of IMPS's expected tables already exist in this schema.
    Lets setup_database() below detect a reinstall against a database
    that already has real data in it, and ask before dropping anything."""
    cursor.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = %s",
        (schema_name,),
    )
    found = {row[0] for row in cursor.fetchall()}
    return found & EXPECTED_TABLES


def _create_tables(mydb):
    """Run schema.sql's DROP TABLE IF EXISTS / CREATE TABLE statements.
    DESTRUCTIVE -- drops and recreates all of IMPS's tables. Only call
    this once the caller has confirmed that's actually wanted (either
    because no IMPS tables existed yet, or the user explicitly chose
    to start fresh in setup_database() below).

    Returns (ok: bool, error_detail: str | None).
    """
    try:
        with open(SCHEMA_SQL_PATH, "r") as f:
            schema_sql = f.read()

        ### STRIP COMMENT LINES BEFORE SPLITTING ON ';' -- so a comment
        ### block immediately preceding a real statement doesn't get
        ### merged with it into one discarded chunk.
        sql_no_comments = "\n".join(
            line for line in schema_sql.splitlines() if not line.strip().startswith("--")
        )
        statements = [s.strip() for s in sql_no_comments.split(";") if s.strip()]

        cursor = mydb.cursor()
        for statement in statements:
            try:
                cursor.execute(statement)
            except Exception as e:
                ### "TABLE ALREADY EXISTS" IS NOT A REAL FAILURE, SO
                ### DON'T ABORT THE WHOLE RUN OVER IT. errno 1050 is
                ### MySQL/MariaDB's ER_TABLE_EXISTS_ERROR; checked by
                ### errno rather than message text so this doesn't
                ### depend on matching exact wording.
                if getattr(e, "errno", None) == 1050:
                    logger.info(f"Setup wizard: table already exists, skipping: {e}")
                    continue
                raise
        mydb.commit()
        cursor.close()
        return True, None
    except Exception as e:
        logger.error(f"Setup wizard: table creation failed: {e}")
        return False, str(e)


@bp.route("/setup/database", methods=["GET", "POST"])
def setup_database():
    guard = _guard()
    if guard:
        return guard

    conn_ok = None
    tables_ok = None
    error_detail = None
    existing_tables_found = False
    ### table_action is only present on the second POST, after the
    ### user has been shown the "existing tables found" prompt below
    ### and picked "keep" or "recreate". Its absence is what tells us
    ### this is either a brand-new submission (with host/name/user/
    ### password in the form) or a first-time connection test.
    table_action = request.form.get("table_action")

    if request.method == "POST":
        if table_action is None:
            ### FIRST SUBMISSION: WRITE + APPLY THE NEW DB SETTINGS
            host = request.form.get("host", "").strip()
            name = request.form.get("name", "").strip()
            user = request.form.get("user", "").strip()
            password = request.form.get("password", "")

            ### LEFT BLANK == "KEEP WHATEVER'S ALREADY SAVED" (see the
            ### has_saved_password / template note below) -- lets
            ### someone bouncing back and forth fixing host/name/user
            ### without retyping a password they already got right.
            ### Never actually put the saved password's value into
            ### the HTML the way a masked "········" pre-fill would --
            ### that'd leak the real secret into page source just to
            ### fake a masked display.
            if not password:
                password = extensions.dbpass

            extensions.write_config_values(
                "database",
                {"host": host, "name": name, "user": user, "password": password},
            )
            extensions.reload_config()

        ### TEST THE CONNECTION (either against what was just entered,
        ### or -- on the follow-up "keep"/"recreate" POST -- against
        ### whatever's currently in imps_config.toml, which the first
        ### submission already wrote)
        try:
            with get_db_connection() as mydb:
                conn_ok = True
                cursor = mydb.cursor()
                found = _existing_imps_tables(cursor, extensions.dbname)
                cursor.close()

                if table_action == "recreate":
                    ### USER EXPLICITLY CONFIRMED THIS IS OK
                    tables_ok, error_detail = _create_tables(mydb)

                elif table_action == "keep":
                    ### DON'T TOUCH ANYTHING -- JUST CONFIRM WHAT'S
                    ### THERE LOOKS LIKE A COMPLETE IMPS SCHEMA
                    missing = EXPECTED_TABLES - found
                    if missing:
                        existing_tables_found = True
                        tables_ok = False
                        error_detail = (
                            "Kept the existing tables, but these expected "
                            f"table(s) are missing: {', '.join(sorted(missing))}. "
                            "Choose \"start fresh\" below to create them."
                        )
                    else:
                        tables_ok = True

                elif found:
                    ### NO DECISION MADE YET, AND THIS DATABASE ALREADY
                    ### HAS SOME OF IMPS'S TABLES IN IT -- e.g. someone
                    ### wiped first.run and re-triggered this wizard
                    ### against a database that already has real
                    ### inventory data. Don't touch anything until they
                    ### tell us what they want.
                    existing_tables_found = True

                else:
                    ### GENUINELY EMPTY DATABASE -- SAFE TO CREATE
                    ### AUTOMATICALLY, NO PROMPT NEEDED
                    tables_ok, error_detail = _create_tables(mydb)

        except DBConnectionError as e:
            conn_ok = False
            error_detail = str(e)
            logger.error(f"Setup wizard: DB connection test failed: {e}")

    return render_template(
        "setup/setup_database.html",
        conn_ok=conn_ok,
        tables_ok=tables_ok,
        existing_tables_found=existing_tables_found,
        error_detail=error_detail,
        host=request.form.get("host", extensions.dbhost),
        name=request.form.get("name", extensions.dbname),
        user=request.form.get("user", extensions.dbuser),
        has_saved_password=bool(extensions.dbpass),
    )


########################################################################
### OPTIONAL SAMPLE DATA
########################################################################
@bp.route("/setup/samples", methods=["GET", "POST"])
def setup_samples():
    guard = _guard()
    if guard:
        return guard

    if request.method == "POST":
        if request.form.get("install_samples"):
            try:
                from app.sample_data import install_sample_data

                install_sample_data()
            except Exception as e:
                # Best-effort by design (see app/sample_data.py) --
                # don't let a sample-data hiccup block the rest of setup.
                logger.error(f"Setup wizard: sample data install failed: {e}")
        return redirect(url_for("setup.setup_password"))

    return render_template("setup/setup_samples.html")


########################################################################
### SET THE IMPS PASSWORD (SINGLE SHARED ACCOUNT)
########################################################################
@bp.route("/setup/password", methods=["GET", "POST"])
def setup_password():
    guard = _guard()
    if guard:
        return guard

    error = None

    ### FRESH READ, NOT A CACHED VALUE -- extensions.py only ever
    ### keeps a one-way hash of the password (HASHED_IMPS_PASS), which
    ### can't be read back to prefill/compare against, so the current
    ### plaintext value has to come straight from the toml file itself.
    current_password = read_config().get("password", {}).get("password", "")
    has_saved_password = bool(current_password)

    if request.method == "POST":
        new_password = request.form.get("password", "")

        if not new_password:
            ### LEFT BLANK == "KEEP WHATEVER'S ALREADY SAVED", same as
            ### the DB password field on setup_database.html -- lets
            ### someone bouncing back through the wizard (e.g. to fix
            ### a DB setting) without being forced to retype a password
            ### they already set correctly.
            new_password = current_password

        if not new_password:
            error = "Password cannot be blank."
        else:
            ### NO CONFIRM-FIELD MATCH CHECK: setup_password.html only
            ### ever collects the password once (the "Show" toggle
            ### covers the usual reason a confirm field exists), and
            ### there's no confirm_password field in that form to
            ### compare against -- matches control_panel.py's
            ### cp_passwordedited(), which handles the same "set/change
            ### the IMPS password" task the same single-field way.
            extensions.write_config_values("password", {"password": new_password})
            extensions.reload_config()

            ### FINISH SETUP: rename first.run away, same as the
            ### file-rename half of main.del_firstrun() (sample data
            ### is handled separately, back in setup_samples() -- this
            ### route only ever runs after that step, so there's
            ### nothing left to seed here).
            first_run = os.path.join(IMPS_DIR, "first.run")
            not_first_run = os.path.join(IMPS_DIR, "not_first.run")
            try:
                os.rename(first_run, not_first_run)
            except OSError:
                logger.info("Setup wizard: first.run already removed.")

            return redirect(url_for("main.home"))

    return render_template(
        "setup/setup_password.html",
        error=error,
        has_saved_password=has_saved_password,
        current_password=current_password,
    )
