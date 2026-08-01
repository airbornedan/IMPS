########################################################################
### CONTROL PANEL BLUEPRINT — ADMIN: CATEGORIES, LOCATIONS, BACKUPS,
### ORPHANED PHOTO CLEANUP, VIEW/COLUMN PREFERENCES
########################################################################
from flask import Blueprint, request, render_template, redirect, url_for, make_response
import os
import shutil
import subprocess
import time
from datetime import date
from mysql.connector.errors import IntegrityError

from app import extensions
from app.extensions import (
    get_db_connection,
    login_required,
    IMPS_DIR,
    BACKUP_DIR,
    ITEM_IMAGE_DIR,
    ITEM_IMAGE_FS_DIR,
    logger,
    db_errors,
    run_query,
    get_items_per_page,
    ALLOWED_ITEMS_PER_PAGE,
    allowed_file,
    MAX_CATEGORY_NAME_LENGTH,
    MAX_LOCATION_NAME_LENGTH,
    get_or_create_cat_num,
    get_or_create_loc_num,
    safe_image_path,
)

bp = Blueprint("control_panel", __name__)

# How many of the most recent backups to keep per type (db, image)
# before the oldest gets deleted -- both the DB row and the file on
# disk. Applies independently to each type.
BACKUP_HISTORY_KEEP = 4


def _record_backup_and_prune(mydb, backup_type, filename, backup_date):
    """Insert a new backup_history row for this backup, then delete
    the oldest row(s)/file(s) beyond BACKUP_HISTORY_KEEP for that same
    type. Shared by cp_dbbackup and cp_photoarchive so both backup
    kinds behave identically -- round-robin, newest first, oldest
    dropped once the cap is exceeded.
    """
    cursor = mydb.cursor()
    cursor.execute(
        "INSERT INTO backup_history (backup_type, filename, backup_date) VALUES (%s, %s, %s)",
        (backup_type, filename, backup_date),
    )
    cursor.close()

    cursor = mydb.cursor()
    cursor.execute(
        """
        SELECT id, filename FROM backup_history
        WHERE backup_type = %s
        ORDER BY created_at DESC, id DESC
        """,
        (backup_type,),
    )
    all_rows = cursor.fetchall()
    cursor.close()

    stale_rows = all_rows[BACKUP_HISTORY_KEEP:]
    for stale_id, stale_filename in stale_rows:
        # Best effort file removal. If file can't be deleted, clean DB
        # row anyway. stale_filename is from backup_history.filename at
        # backup time, an absolute path from IMPS_DIR in extensions.py.
        # Working directory independent.
        try:
            os.remove(stale_filename)
        except OSError as e:
            logger.error(f"Could not remove stale backup file '{stale_filename}': {e}")

        cursor = mydb.cursor()
        cursor.execute("DELETE FROM backup_history WHERE id = %s", (stale_id,))
        cursor.close()


########################################################################
### CONTROL PANEL -- SETTINGS/BOX-ITEM TAB (default landing page)
# Four separate routes, one per tab, each a real bookmarkable page
# with its own help topic. Tab bar is a shared include
# (templates/includes/cp_tabs.html); see that file for "active tab"
# highlighting.
@bp.route("/control_panel")
@login_required
def controlpanel():
    return render_template("control_panel/control_panel.html")


########################################################################
### CONTROL PANEL -- BACKUPS TAB
@bp.route("/cp_backups")
@login_required
@db_errors(exec_msg="Database error when reading backup history.")
def cp_backups():
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### READ THE MOST RECENT BACKUP_HISTORY_KEEP ROWS PER BACKUP
        ### TYPE, NEWEST FIRST. Empty is valid (fresh install, no
        ### backups yet), not an error. Template shows no "last
        ### backup" link in that case.
        cursor = mydb.cursor()
        cursor.execute(
            """
            SELECT filename, backup_date FROM backup_history
            WHERE backup_type = 'db'
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (BACKUP_HISTORY_KEEP,),
        )
        db_backups = cursor.fetchall()
        cursor.close()

        cursor = mydb.cursor()
        cursor.execute(
            """
            SELECT filename, backup_date FROM backup_history
            WHERE backup_type = 'image'
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (BACKUP_HISTORY_KEEP,),
        )
        image_backups = cursor.fetchall()
        cursor.close()

    return render_template(
        "control_panel/cp_backups.html",
        db_backups=db_backups,
        image_backups=image_backups,
    )


########################################################################
### CONTROL PANEL -- CLEANUP TAB (launcher; cleanup tools live at
### their own routes, /cp_orphaneditemscleanup and /cp_photofilescleanup)
@bp.route("/cp_cleanup")
@login_required
def cp_cleanup():
    return render_template("control_panel/cp_cleanup.html")


########################################################################
### CONTROL PANEL -- SERVER TAB (read-only config display)
@bp.route("/cp_server")
@login_required
def cp_server():
    ### OBSCURE PASSWORD MAPPING VARIABLES
    ### (read via extensions module: reflects wizard credential changes
    ### immediately)
    obscure_pass = "*" * len(extensions.dbpass) if extensions.dbpass else ""

    return render_template(
        "control_panel/cp_server.html",
        dbhost=extensions.dbhost,
        dbname=extensions.dbname,
        dbuser=extensions.dbuser,
        dbpass=obscure_pass,
        ITEM_IMAGE_DIR=ITEM_IMAGE_FS_DIR,
        BACKUP_DIR=BACKUP_DIR,
    )


########################################################################
# SECURITY: POST-only. Runs mysqldump (disk + subprocess cost) and
# writes a new file every call, no confirmation. GET routes are exempt
# from CSRFProtect's token check, so a GET here would let any page
# loaded in a logged-in admin's browser (img tag, link, crawler)
# trigger a backup with no token check -- POST keeps this covered by
# CSRFProtect. Not destructive like boxdeletesuccess, but still an
# unauthorized-trigger / mild-DoS vector. No confirmation dialog
# needed -- creating a backup isn't a warn-before-doing action, unlike
# a delete.
@bp.route("/cp_dbbackup", methods=["POST"])
@login_required
@db_errors(exec_msg="Database logging error during backup configuration storage lifecycle.")
def cp_dbbackup():
    ### START BACKUP PROCESS
    backup_time = str(time.time())
    backup_file = os.path.join(BACKUP_DIR, f"{extensions.dbname}-{backup_time}.sql")

    # Runs mysqldump directly (no shell), explicit argument list --
    # shell-metacharacter injection isn't possible. Password passed via
    # MYSQL_PWD env var, not the command line, since command-line args
    # are visible to other local processes via `ps`/`/proc`.
    dump_env = os.environ.copy()
    dump_env["MYSQL_PWD"] = extensions.dbpass

    try:
        with open(backup_file, "wb") as outfile:
            subprocess.run(
                ["mysqldump", "-u", extensions.dbuser, extensions.dbname],
                stdout=outfile,
                stderr=subprocess.PIPE,
                env=dump_env,
                check=True,
            )
    except (subprocess.CalledProcessError, OSError) as e:
        logger.error(f"mysqldump failed in cp_dbbackup: {e}")
        return render_template(
            "errorpage.html",
            err_message="Backup failed. Could not run mysqldump.",
            err_page_from="/",
        )

    today = str(date.today())

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### RECORD IN ROUND-ROBIN HISTORY (KEEPS MOST RECENT
        ### BACKUP_HISTORY_KEEP, PRUNES OLDER: DB ROW AND FILE)
        _record_backup_and_prune(mydb, "db", backup_file, today)

    ### RENDER PAGE
    return render_template("control_panel/cp_dbbackup.html", backup_file=backup_file)


########################################################################
### CREATE PHOTO ARCHIVE AND LOG TO DB
# SECURITY: POST-only, same reasoning as cp_dbbackup above. Calls
# shutil.make_archive over the whole item-image directory every hit;
# GET routes are exempt from CSRFProtect's token check, so POST is
# what keeps this covered.
@bp.route("/cp_photoarchive", methods=["POST"])
@login_required
@db_errors(exec_msg="Database logging error during image compression archiving lifecycle.")
def cp_photoarchive():
    ### CREATE AN ARCHIVE OF PHOTOS (SYSTEM FILE IO)
    today = str(date.today())
    # Time component, not just date: same-day archiving produces
    # distinct files instead of overwriting. Needed since
    # BACKUP_HISTORY_KEEP keeps several archives in rotation.
    archive_file = os.path.join(BACKUP_DIR, f"imps_imagearchive.{today}-{time.time()}")
    archive_start_location = ITEM_IMAGE_FS_DIR
    shutil.make_archive(archive_file, "zip", archive_start_location)

    ### ADD EXTENSION TO FILENAME FOR DB WRITE
    archive_file = f"{archive_file}.zip"

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### RECORD IN ROUND-ROBIN HISTORY (KEEPS MOST RECENT
        ### BACKUP_HISTORY_KEEP, PRUNES OLDER: DB ROW AND FILE)
        _record_backup_and_prune(mydb, "image", archive_file, today)

    ### RETURN PAGE
    return render_template(
        "control_panel/cp_photoarchive.html", archive_file=archive_file
    )


########################################################################
### CONTROL PANEL CATEGORIES MANAGER
@bp.route("/cp_categories")
@login_required
@db_errors(exec_msg="Database reading error when processing layout categorizations.")
def cp_categories():
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. PULL MASTER DEFINITIONS FOR ALL REGISTERED CATEGORIES
        cat_name_num_query = "SELECT cat_name, cat_num FROM categories ORDER BY cat_name;"
        cursor = mydb.cursor()
        cursor.execute(cat_name_num_query)
        categories_master = cursor.fetchall()
        cursor.close()

        if not categories_master:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access category master definitions.",
                err_page_from="/",
            )

        ### 2. QUERY ITEM QUANTITIES PER CATEGORY (AGGREGATION)
        cats_with_items_query = "SELECT cat_num, COUNT(1) FROM items GROUP BY cat_num;"
        cursor = mydb.cursor()
        cursor.execute(cats_with_items_query)
        item_counts_raw = cursor.fetchall()
        cursor.close()

    ### CONVERT ITEM COUNT ASSIGNMENTS INTO AN OPTIMIZED LOOKUP DICTIONARY
    counts_lookup = {row[0]: row[1] for row in item_counts_raw}

    ### MERGE RELATIONSHIPS INTO A CLEAN TUPLE SET
    items_per_cat = []
    for row in categories_master:
        name = row[0]
        num = row[1]

        # Defaults to 0 if the category has no items
        count = counts_lookup.get(num, 0)
        items_per_cat.append((name, count, num))

    items_per_cat.sort(key=lambda x: x[0])

    ### LIST OF EXISTING CATEGORY NAMES FOR CLIENT-SIDE DUPLICATE CHECKING
    # cat_name has a UNIQUE constraint; DB rejects duplicates anyway.
    # This lets the UI catch it immediately instead of a raw DB error.
    available_categories = [row[0] for row in categories_master]

    ### RETURN SUCCESS
    return render_template(
        "control_panel/cp_categories.html",
        items_per_category=items_per_cat,
        available_categories=available_categories,
    )


########################################################################
### DISCOVER ORPHANED FILE IMAGES
@bp.route("/cp_photofilescleanup")
@login_required
@db_errors(exec_msg="Database error when analyzing catalog assets.")
def cp_photofilescleanup():
    # Fetch an active, thread-safe connection from the pool
    photo_files_query = "SELECT item_pic FROM items;"
    result = run_query(photo_files_query)

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Database error. Could not access photos.",
            err_page_from="/",
        )

    ### EXTRACT NAMES FROM RESULT ROWS
    num_items = len(result)
    item_list = [row[0] for row in result if row[0]]
    item_list.sort()

    ### READ ALL FILES IN PHYSICAL DIRECTORY
    # Filtered to recognized image extensions (see allowed_file() in
    # extensions.py). Stray non-image files are never treated as
    # deletable "orphaned photos".
    files_in_dir = [f for f in os.listdir(ITEM_IMAGE_FS_DIR) if allowed_file(f)]
    files_in_dir.sort()

    ### FIND ORPHAN ENTRIES USING SET DIFFERENCING
    orphans = list(set(files_in_dir).difference(item_list))
    
    # Remove placeholder image if present
    if "none.jpg" in orphans:
        orphans.remove("none.jpg")

    return render_template(
        "control_panel/cp_photofilescleanup.html",
        file_names_in_db=item_list,
        orphans=orphans,
        num_items=num_items,
        from_cp=True,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
    )


########################################################################
### EXECUTE DELETION OF ORPHANED IMAGE FILES
@bp.route("/cp_photofilesdel", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error when analyzing or rebuilding catalog assets.")
def cp_photofilesdel():
    ### GET LIST OF FILES FROM THE FORM
    file_list = request.form.getlist("filename")
    checkbox_list = request.form.getlist("checkbox")
    requested_deletions = []

    ### MAP AND RE-ASSEMBLE INDEX POSITION CHECKBOXES TO FILE NAMES
    for x in range(len(file_list)):
        if str(x + 1) in checkbox_list:
            requested_deletions.append(str(file_list[x]))

    ### SECURITY: NEVER TRUST CLIENT-SUPPLIED FILENAMES FOR A FILESYSTEM
    ### DELETE. Recompute orphan set server-side (DB photo references
    ### vs. actual image directory contents). Only delete files that
    ### resolve to a real path inside image_dir (see safe_image_path()
    ### in extensions.py) and are genuinely in that orphan set. Closes
    ### path-traversal deletes (e.g. filename=../../../../etc/passwd):
    ### attacker can only select files this route already considers
    ### orphaned.
    photo_files_query = "SELECT item_pic FROM items;"
    result = run_query(photo_files_query)

    if not result:
        return render_template(
            "errorpage.html",
            err_message="Database error. Could not access files.",
            err_page_from="/",
        )

    item_list = [row[0] for row in result if row[0]]
    item_list.sort()

    image_dir = ITEM_IMAGE_FS_DIR
    files_in_dir = [f for f in os.listdir(image_dir) if allowed_file(f)]
    files_in_dir.sort()

    orphans = set(files_in_dir).difference(item_list)
    orphans.discard("none.jpg")

    files_to_del = [
        f for f in requested_deletions if f in orphans and safe_image_path(f, image_dir)
    ]

    ### DELETE FILES ON DISK
    for filename_to_remove in files_to_del:
        try:
            os.remove(os.path.join(image_dir, filename_to_remove))
        except Exception as file_error:
            logger.error(f"System File deletion error: {file_error}")
            return render_template(
                "errorpage.html",
                err_message="Some structural target files could not be deleted from disk storage.",
                err_page_from="/cp_photofilescleanup",
            )

    # Fetch an active, thread-safe connection from the pool
    photo_files_query = "SELECT item_pic FROM items;"
    result = run_query(photo_files_query)

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Database error. Could not access files.",
            err_page_from="/",
        )

    ### RE-QUERY AFTER DELETION
    item_list = [row[0] for row in result if row[0]]
    item_list.sort()

    ### RE-READ STORAGE FILE DIRECTORY AND RECALCULATE RE-INDEXED ORPHANS
    files_in_dir = [f for f in os.listdir(ITEM_IMAGE_FS_DIR) if allowed_file(f)]
    files_in_dir.sort()

    orphans = list(set(files_in_dir).difference(item_list))
    if "none.jpg" in orphans:
        orphans.remove("none.jpg")

    ### SHOW THE REFRESHED CLEANUP PAGE
    return render_template(
        "control_panel/cp_photofilescleanup.html",
        file_names_in_db=item_list,
        orphans=orphans,
        from_cp=True,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
    )


########################################################################
### BULK DELETE ALL ORPHANED IMAGE FILES
@bp.route("/cp_delallorphanphotos", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error when fetching directory assets map.")
def cp_delallorphanphotos():
    # Fetch an active, thread-safe connection from the pool
    photo_files_query = "SELECT item_pic FROM items;"
    result = run_query(photo_files_query)

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Database error. Could not access photos.",
            err_page_from="/",
        )

    ### EXTRACT NAMES FROM RESULT ROWS
    item_list = [row[0] for row in result if row[0]]
    item_list.sort()

    ### READ ALL FILES IN PHYSICAL DIRECTORY
    # Same image-extension filter as cp_photofilescleanup() above.
    # Especially important here: this route deletes every file in the
    # orphan set immediately, no per-file confirmation.
    files_in_dir = [f for f in os.listdir(ITEM_IMAGE_FS_DIR) if allowed_file(f)]
    files_in_dir.sort()

    ### CREATE A LIST OF IMAGES IN DIR BUT NOT IN DB
    orphans = list(set(files_in_dir).difference(item_list))

    ### EXCLUDE DEFAULT PLACEHOLDER IMAGE
    if "none.jpg" in orphans:
        orphans.remove("none.jpg")

    ### DELETE FILES OUTSIDE THE DB CONNECTION -- a slow filesystem
    ### shouldn't hold a pooled connection open
    for orphan_file in orphans:
        try:
            os.remove(os.path.join(ITEM_IMAGE_FS_DIR, orphan_file))
        except Exception as file_error:
            logger.error(f"System File deletion error during mass purge: {file_error}")
            return render_template(
                "errorpage.html",
                err_message="Some files could not be deleted from physical disk storage.",
                err_page_from="/cp_photofilescleanup",
            )

    ### SHOW THE REFRESHED CLEANUP PAGE
    return redirect(url_for("control_panel.cp_photofilescleanup"))


########################################################################
### DISPATCH SINGLE CATEGORY EDIT PAGE
@bp.route("/cp_editcat/<cat_num>")
@login_required
@db_errors(exec_msg="Database error when fetching category details.")
def cp_editcat(cat_num):
    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(cat_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Category entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### SET UP CATEGORY QUERY
        category_query = """ SELECT cat_name FROM categories WHERE cat_num = %s """
        cursor = mydb.cursor()
        cursor.execute(category_query, (cat_num,))
        result = cursor.fetchone()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access category record data.",
                err_page_from="/",
            )
        cat_name = result[0]

        ### 'UNCATEGORIZED' IS PROTECTED. cp_categories.html disables its
        ### edit button client-side, but that's cosmetic. Real
        ### enforcement is here: a direct URL hit (or JS disabled)
        ### shouldn't rename the fallback category for uncategorized items.
        if cat_name == "Uncategorized":
            return render_template(
                "errorpage.html",
                err_message='"Uncategorized" is a protected category and cannot be edited.',
                err_page_from="/control_panel/cp_categories",
            )

        ### LIST OF ALL OTHER CATEGORY NAMES, FOR CLIENT-SIDE DUPLICATE
        ### CHECKING (excludes this category's own name -- saving the
        ### form unchanged shouldn't trip a "duplicate" warning)
        all_cats_query = """ SELECT cat_name FROM categories """
        cursor = mydb.cursor()
        cursor.execute(all_cats_query)
        all_cats_result = cursor.fetchall()
        cursor.close()

        other_categories = [row[0] for row in all_cats_result if row[0] != cat_name]

    ### SHOW THE PAGE
    return render_template(
        "control_panel/cp_catedit.html",
        cat_name=cat_name,
        cat_num=cat_num,
        other_categories=other_categories,
    )



########################################################################
### SAVE CATEGORY NAME MODIFICATIONS AND PROPAGATE DEPENDENCIES
@bp.route("/cp_cateditsuccess/<cat_num>", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error. Changes could not be processed fully across inventory assets.")
def cp_cateditsuccess(cat_num):
    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(cat_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Category entry is not a number.",
            err_page_from="/",
        )

    # GET VALUES FROM FORM
    form_cat_num = request.form.get("cat_num")
    cat_name = request.form.get("cat_name") or ""

    ### VALIDATE CATEGORY NAME LENGTH. Edit form enforces this
    ### client-side (maxlength="64" + JS, see cp_catedit.html), but a
    ### direct POST bypasses that.
    if len(cat_name) > MAX_CATEGORY_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=f"Category names are limited to {MAX_CATEGORY_NAME_LENGTH} characters.",
            err_page_from=f"/cp_editcat/{cat_num}",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. SAME PROTECTION AS cp_editcat. This route writes the
        ### change and can be POSTed to directly, bypassing the edit
        ### page above.
        get_old_cat_query = """ SELECT cat_name FROM categories WHERE cat_num = %s """
        cursor = mydb.cursor()
        cursor.execute(get_old_cat_query, (form_cat_num,))
        result = cursor.fetchone()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Target category reference no longer exists.",
                err_page_from="/",
            )
        old_cat_name = result[0]

        if old_cat_name == "Uncategorized":
            return render_template(
                "errorpage.html",
                err_message='"Uncategorized" is a protected category and cannot be edited.',
                err_page_from="/control_panel/cp_categories",
            )

        ### 2. UPDATE THE CATEGORIES MASTER RECORD -- the only write this
        ### route needs. Items reference cat_num (a real foreign key)
        ### rather than a copy of the name, so every item "sees" the new
        ### name the instant this row changes, via the join every read
        ### query does (see ITEMS_WITH_CAT_NAME in items.py).
        #
        # Caught here, not the @db_errors decorator's generic handler:
        # UNIQUE constraint on categories.cat_name can raise
        # IntegrityError, and the message needs request-specific
        # cat_name/cat_num values a decorator argument can't provide.
        # Already checked client-side in cp_catedit.html's JS; fires
        # only if JS is disabled or two admins rename to the same name
        # at once.
        update_cat_query = """ UPDATE categories SET cat_name = %s WHERE cat_num = %s """
        cursor = mydb.cursor()
        try:
            cursor.execute(update_cat_query, (cat_name, form_cat_num))
        except IntegrityError as e:
            logger.error(f"Duplicate category name in cp_cateditsuccess: {e}")
            return render_template(
                "errorpage.html",
                err_message=f'A category named "{cat_name}" already exists. Please choose a different name.',
                err_page_from=f"/cp_editcat/{cat_num}",
            )
        cursor.close()

    return redirect(url_for("control_panel.cp_categories"))


########################################################################
### DISPATCH CATEGORY DELETION CONFIRMATION DIALOG
@bp.route("/cp_delcat/<cat_num>")
@login_required
@db_errors(exec_msg="Database error when fetching category details.")
def cp_catdel(cat_num):
    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(cat_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Category entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    category_query = """ SELECT cat_name FROM categories WHERE cat_num = %s """
    result = run_query(category_query, (cat_num,), fetch="one")

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Category does not exist.",
            err_page_from="/",
        )
    cat_name = result[0]

    ### SAME PROTECTION AS cp_editcat -- Uncategorized can't be deleted
    if cat_name == "Uncategorized":
        return render_template(
            "errorpage.html",
            err_message='"Uncategorized" is a protected category and cannot be deleted.',
            err_page_from="/control_panel/cp_categories",
        )

    return render_template(
        "control_panel/cp_catdelconf.html", 
        cat_name=cat_name, 
        cat_num=cat_num
    )


########################################################################
### EXECUTE CATEGORY DELETION AND REASSIGN DEPENDENCIES
@bp.route("/cp_catdelsuccess/<cat_num>", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error. Could not safely remove category or reassign inventory contents.")
def cp_catdelsuccess(cat_num):
    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(cat_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. QUERY TO GET THE CATEGORY NAME BEFORE REMOVING IT
        get_cat_query = """ SELECT cat_name FROM categories WHERE cat_num = %s """
        cursor = mydb.cursor()
        cursor.execute(get_cat_query, (cat_num,))
        result = cursor.fetchone()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access target category.",
                err_page_from="/",
            )
        cat_name = result[0]

        ### SAME PROTECTION AS cp_editcat/cp_catdel. This route deletes
        ### the row and can be POSTed to directly. items.cat_num has
        ### ON DELETE RESTRICT (see deploy/schema.sql), so without the
        ### reassignment step below (2), deleting an in-use category
        ### would raise a raw FK-constraint error instead.
        if cat_name == "Uncategorized":
            return render_template(
                "errorpage.html",
                err_message='"Uncategorized" is a protected category and cannot be deleted.',
                err_page_from="/control_panel/cp_categories",
            )

        ### 2. REASSIGN ITEMS MATCHING THIS CATEGORY TO 'UNCATEGORIZED'.
        ### Resolved by NAME rather than hardcoding cat_num 0 -- 0 is
        ### only guaranteed to be Uncategorized's id on a fresh install
        ### (see deploy/schema.sql's seed data). Elsewhere, Uncategorized's
        ### cat_num is whatever AUTO_INCREMENT assigned it, so hardcoding
        ### 0 could point at a cat_num that doesn't exist, raising the
        ### exact FK error this reassignment exists to avoid.
        cursor = mydb.cursor()
        uncategorized_cat_num = get_or_create_cat_num(cursor, "Uncategorized")
        cursor.close()

        update_item_cat_query = """ UPDATE items SET cat_num = %s WHERE cat_num = %s """
        cursor = mydb.cursor()
        cursor.execute(update_item_cat_query, (uncategorized_cat_num, cat_num))
        cursor.close()

        ### 3. DELETE THE CATEGORY MASTER RECORD
        del_cat_query = """ DELETE FROM categories WHERE cat_num = %s """
        cursor = mydb.cursor()
        cursor.execute(del_cat_query, (cat_num,))
        cursor.close()

    ### RETURN TO CATEGORY LIST PAGE
    return redirect(url_for("control_panel.cp_categories"))


########################################################################
### REDIRECT TO THE REAL BULK-DELETE ENDPOINT
@bp.route("/cp_delallorphans", methods=["POST"])
@login_required
def cp_delallorphans():
    # Routed redirect to the functional mass removal endpoint. A 307
    # preserves the POST method/body on the redirect instead of letting
    # the browser turn it into a GET.
    return redirect(url_for("control_panel.cp_delallorphanphotos"), code=307)


########################################################################
### CREATE NEW CATEGORY RECORD ENTRY
@bp.route("/cp_addcat", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error. Could not populate new category record definitions.")
def cp_addcat():
    new_cat = request.form.get("new_cat") or ""

    ### VALIDATE CATEGORY NAME LENGTH -- the "add category" form
    ### already enforces this client-side via maxlength="64" + JS (see
    ### cp_categories.html), but that's client-side only; a direct
    ### POST bypasses it entirely.
    if len(new_cat) > MAX_CATEGORY_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=f"Category names are limited to {MAX_CATEGORY_NAME_LENGTH} characters.",
            err_page_from="/cp_categories",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### ADD CATEGORY TO DB
        # Caught here, not the @db_errors decorator's generic handler:
        # UNIQUE constraint on categories.cat_name can raise
        # IntegrityError, and the message needs the request-specific
        # new_cat value a decorator argument can't provide. The "add
        # category" form already checks this client-side; fires only
        # if JS is disabled or two admins submit the same name at once.
        add_cat_query = """ INSERT INTO categories (cat_num, cat_name) VALUES (NULL, %s) """
        cursor = mydb.cursor()
        try:
            cursor.execute(add_cat_query, (new_cat,))
        except IntegrityError as e:
            logger.error(f"Duplicate category name in cp_addcat: {e}")
            return render_template(
                "errorpage.html",
                err_message=f'A category named "{new_cat}" already exists. Please choose a different name.',
                err_page_from="/cp_categories",
            )
        cursor.close()

    ### RETURN TO CATEGORY LIST PAGE
    return redirect(url_for("control_panel.cp_categories"))



########################################################################
### SHOW ALL ORPHANED ITEMS (ITEMS WITHOUT A BOX ASSIGNED)
@bp.route("/cp_orphaneditemscleanup")
@login_required
@db_errors(exec_msg="Database error when fetching unassigned inventory assets.")
def cp_orphan_list():
    # Fetch an active, thread-safe connection from the pool
    find_orphans_query = """ SELECT i.item_num, i.item_name, i.box_num, i.item_pic, i.item_date,
                                     c.cat_name AS item_cat, i.item_desc
                              FROM items i
                              JOIN categories c ON i.cat_num = c.cat_num
                              WHERE i.box_num IS NULL; """
    result = run_query(find_orphans_query, as_dict=True)

    ### READ THE COLUMN COOKIES
    info_column = request.cookies.get("info_column")
    photo_column = request.cookies.get("photo_column")
    date_column = request.cookies.get("date_column")
    cat_column = request.cookies.get("cat_column")
    box_column = request.cookies.get("box_column")

    ### (cp_orphanlist.html branches internally on current_view for
    ### mobile vs desktop markup, based on the view cookie)
    current_view = request.cookies.get("view")
    return render_template(
        "control_panel/cp_orphanlist.html",
        current_view=current_view,
        item_list=result,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        cookies=request.cookies,
        info_column=info_column,
        photo_column=photo_column,
        date_column=date_column,
        cat_column=cat_column,
        box_column=box_column,
    )


########################################################################
### SWITCH ORPHAN VIEW (FLIP DISPLAY COOKIE)
@bp.route("/orphan_view_switch")
@login_required
@db_errors(exec_msg="Database error when filtering inventory views.")
def orphan_vs():
    # Fetch an active, thread-safe connection from the pool
    find_orphans_query = """ SELECT i.item_num, i.item_name, i.box_num, i.item_pic, i.item_date,
                                     c.cat_name AS item_cat, i.item_desc
                              FROM items i
                              JOIN categories c ON i.cat_num = c.cat_num
                              WHERE i.box_num IS NULL; """
    result = run_query(find_orphans_query, as_dict=True)

    ### READ THE COLUMN COOKIES
    info_column = request.cookies.get("info_column")
    photo_column = request.cookies.get("photo_column")
    date_column = request.cookies.get("date_column")
    cat_column = request.cookies.get("cat_column")
    box_column = request.cookies.get("box_column")

    ### GET COOKIE TO DETERMINE VIEW
    current_view = request.cookies.get("view")

    ### THIS ROUTE FLIPS THE VIEW: render the opposite of current_view,
    ### and set the cookie to match what was just rendered.
    new_view = "desk" if current_view == "mobile" else "mobile"
    response = make_response(
        render_template(
            "control_panel/cp_orphanlist.html",
            current_view=new_view,
            item_list=result,
            ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            IMPS_DIR=IMPS_DIR,
            cookies=request.cookies,
            info_column=info_column,
            photo_column=photo_column,
            date_column=date_column,
            cat_column=cat_column,
            box_column=box_column,
        )
    )
    response.set_cookie("view", new_view)
    return response


########################################################################
### CONTROL PANEL LOCATIONS DASHBOARD
@bp.route("/cp_locations")
@login_required
@db_errors(exec_msg="Database reading error when processing dashboard statistics.")
def cp_locations():
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. PULL MASTER DEFINITIONS FOR ALL REGISTERED LOCATIONS
        loc_name_num_query = "SELECT loc_name FROM locations ORDER BY loc_name;"
        cursor = mydb.cursor()
        cursor.execute(loc_name_num_query)
        locations_result = cursor.fetchall()
        cursor.close()

        if not locations_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access locations records.",
                err_page_from="/",
            )

        ### 2. QUANTITY OF BOXES ASSIGNED PER LOCATION, IN ONE QUERY
        # Avoids N separate queries, one per location.
        box_by_loc_query = """ SELECT loc_num, COUNT(*) FROM boxes GROUP BY loc_num; """
        cursor = mydb.cursor()
        cursor.execute(box_by_loc_query)
        box_counts_raw = cursor.fetchall()
        cursor.close()

        ### 3. PULL loc_num ALONGSIDE loc_name SO THE COUNTS ABOVE
        ### (KEYED BY loc_num) CAN BE MATCHED BACK UP TO EACH NAME
        loc_num_query = "SELECT loc_name, loc_num FROM locations ORDER BY loc_name;"
        cursor = mydb.cursor()
        cursor.execute(loc_num_query)
        loc_nums_result = cursor.fetchall()
        cursor.close()

    ### PARSE EXTRACTED MASTER LOCATIONS LIST
    locations = [row[0] for row in locations_result]

    ### CONVERT AGGREGATED BOX QUANTITIES INTO A LOOKUP DICTIONARY
    counts_lookup = {row[0]: row[1] for row in box_counts_raw}
    name_to_num = {row[0]: row[1] for row in loc_nums_result}

    ### MERGE COUNTS BACK ONTO EACH LOCATION NAME
    loc_count = []
    for loc_name in locations:
        # Defaults to 0 if the location has no boxes
        loc_count.append(counts_lookup.get(name_to_num.get(loc_name), 0))

    ### SHOW LOCATION PAGE
    return render_template(
        "control_panel/cp_locations.html", 
        locations=locations, 
        loc_count=loc_count
    )



########################################################################
### DISPATCH LOCATION EDIT PAGE WITH VALIDATION
@bp.route("/cp_editloc/<loc_name>")
@login_required
@db_errors(
    conn_msg="Database error accessing locations. Could not connect.",
    exec_msg="Database error when analyzing location validation logs.",
)
def cp_editloc(loc_name):
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. PULL ALL LOCATIONS TO VERIFY ROUTE ARGUMENT PARAMETERS
        loc_name_num_query = "SELECT loc_name FROM locations ORDER BY loc_name;"
        cursor = mydb.cursor()
        cursor.execute(loc_name_num_query)
        all_locs_result = cursor.fetchall()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not all_locs_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access locations.",
                err_page_from="/",
            )

        ### EXTRACT LOCATION NAMES
        locations = [row[0] for row in all_locs_result]

        ### VERIFY ROUTE DECORATOR INPUT VALUES MATCH KNOWN ENTRIES
        if loc_name not in locations:
            return render_template(
                "errorpage.html",
                err_message="Invalid location. The location entered is not in the database",
                err_page_from="/control_panel/cp_locations",
            )

        ### 'UNSPECIFIED' IS PROTECTED -- cp_locations.html disables its
        ### edit button client-side, but that's cosmetic only. This is
        ### the real enforcement: boxes.loc_num falls back to this
        ### value (see boxadded() in boxes.py), so it must always exist.
        if loc_name == "Unspecified":
            return render_template(
                "errorpage.html",
                err_message='"Unspecified" is a protected location and cannot be edited.',
                err_page_from="/control_panel/cp_locations",
            )

        ### 2. QUERY TO GET THE LOCATION REFERENCE ID BASED ON VALID NAME
        loc_num_query = """ SELECT loc_num FROM locations WHERE loc_name = %s; """
        cursor = mydb.cursor()
        cursor.execute(loc_num_query, (loc_name,))
        num_result = cursor.fetchone()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not num_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access locations reference key IDs.",
                err_page_from="/",
            )
        loc_num = num_result[0]

    ### DISPATCH FORM TEMPLATE
    return render_template(
        "control_panel/cp_locedit.html",
        old_loc_name=loc_name,
        old_loc_num=loc_num,
        locations=locations,
    )


########################################################################
### CREATE NEW SYSTEM TRACKING LOCATION ENTRY
@bp.route("/cp_addloc", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error. Could not append new location record definition.")
def cp_addloc():
    new_loc = request.form.get("new_loc") or ""

    ### VALIDATE LOCATION NAME LENGTH -- the "add location" form
    ### enforces this client-side via maxlength + JS (see
    ### cp_locations.html), but that's client-side only; a direct POST
    ### bypasses it entirely.
    if len(new_loc) > MAX_LOCATION_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=f"Location names are limited to {MAX_LOCATION_NAME_LENGTH} characters.",
            err_page_from="/cp_locations",
        )

    # Caught here, not the @db_errors decorator's generic handler:
    # UNIQUE constraint on locations.loc_name can raise IntegrityError,
    # and the message needs the request-specific new_loc value a
    # decorator argument can't provide. The "add location" form doesn't
    # check this client-side yet (see cp_locations.html), so this is the
    # only guard against duplicate submissions.
    add_loc_query = """ INSERT INTO locations (loc_num, loc_name) VALUES (NULL, %s) """
    try:
        run_query(add_loc_query, (new_loc,), fetch=None)
    except IntegrityError as e:
        logger.error(f"Duplicate location name in cp_addloc: {e}")
        return render_template(
            "errorpage.html",
            err_message=f'A location named "{new_loc}" already exists. Please choose a different name.',
            err_page_from="/cp_locations",
        )

    ### RETURN TO LOCATION LIST PAGE
    return redirect(url_for("control_panel.cp_locations"))

########################################################################
### SUBMIT SYSTEM LOCATION CHANGES AND PROPAGATE UPDATE
@bp.route("/cp_locedited/", methods=["POST"])
@login_required
@db_errors(
    conn_msg="Database error accessing locations. Could not connect.",
    exec_msg="Database error. Changes could not be processed fully across locations map.",
)
def cp_locedited():
    ### GET FORM DATA
    loc_num = request.form.get("loc_num")
    new_loc_name = request.form.get("new_loc_name") or ""
    old_loc_name = request.form.get("old_loc_name")

    ### VALIDATE LOCATION NAME LENGTH -- the edit form enforces this
    ### client-side via maxlength + JS (see cp_locedit.html), but a
    ### direct POST bypasses it entirely.
    if len(new_loc_name) > MAX_LOCATION_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=f"Location names are limited to {MAX_LOCATION_NAME_LENGTH} characters.",
            err_page_from=f"/cp_editloc/{old_loc_name}",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. SET UP LOCATIONS QUERY TO VERIFY ROUTE ARGUMENTS
        loc_name_num_query = "SELECT loc_name FROM locations ORDER BY loc_name;"
        cursor = mydb.cursor()
        cursor.execute(loc_name_num_query)
        loc_result = cursor.fetchall()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not loc_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access locations.",
                err_page_from="/",
            )

        ### EXTRACT NAMES FROM RESULT ROWS
        locations = [row[0] for row in loc_result]

        ### VERIFY WE ARE UPDATING A KNOWN LOCATION
        if old_loc_name not in locations:
            return render_template(
                "errorpage.html",
                err_message="Invalid location. The location entered is not in the database",
                err_page_from="/cp_locations",
            )

        ### SAME PROTECTION AS cp_editloc. This route writes the
        ### change and can be POSTed to directly, bypassing the edit
        ### page above.
        if old_loc_name == "Unspecified":
            return render_template(
                "errorpage.html",
                err_message='"Unspecified" is a protected location and cannot be edited.',
                err_page_from="/control_panel/cp_locations",
            )

        ### 2. EXECUTE QUERY TO UPDATE LOCATION NAME
        # Caught here, not the @db_errors decorator's generic handler:
        # UNIQUE constraint on locations.loc_name can raise
        # IntegrityError, and the message needs the request-specific
        # new_loc_name/loc_num values a decorator argument can't
        # provide. Mirrors cp_cateditsuccess()'s handling for categories.
        loc_update_query = """ UPDATE locations SET loc_name = %s WHERE loc_num = %s; """
        cursor = mydb.cursor()
        try:
            cursor.execute(loc_update_query, (new_loc_name, loc_num))
        except IntegrityError as e:
            logger.error(f"Duplicate location name in cp_locedited: {e}")
            return render_template(
                "errorpage.html",
                err_message=f'A location named "{new_loc_name}" already exists. Please choose a different name.',
                err_page_from=f"/cp_editloc/{old_loc_name}",
            )
        cursor.close()

    ### RETURN TO LOCATION LIST PAGE
    return redirect(url_for("control_panel.cp_locations"))


########################################################################
### DISPATCH LOCATION DELETION CONFIRMATION DIALOG
@bp.route("/cp_delloc/<loc_name>")
@login_required
@db_errors(
    conn_msg="Database error accessing locations. Could not connect.",
    exec_msg="Database error when fetching location details.",
)
def cp_delloc(loc_name):
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. PULL MASTER DEFINITIONS TO VERIFY ROUTE DECORATOR PARAMETERS
        loc_name_num_query = "SELECT loc_name FROM locations ORDER BY loc_name;"
        cursor = mydb.cursor()
        cursor.execute(loc_name_num_query)
        loc_result = cursor.fetchall()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not loc_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access locations.",
                err_page_from="/",
            )

        ### EXTRACT NAMES FROM RESULT ROWS
        locations = [row[0] for row in loc_result]

        ### VERIFY ROUTE DECORATOR IS A KNOWN LOCATION
        if loc_name not in locations:
            return render_template(
                "errorpage.html",
                err_message="Invalid location. The location entered is not in the database",
                err_page_from="/control_panel/cp_locations",
            )

        ### SAME PROTECTION AS cp_editloc -- Unspecified can't be deleted
        if loc_name == "Unspecified":
            return render_template(
                "errorpage.html",
                err_message='"Unspecified" is a protected location and cannot be deleted.',
                err_page_from="/control_panel/cp_locations",
            )

        ### 2. QUERY TO GET LOCATION ID REFERENCE KEY BASED ON VALID NAME
        loc_num_query = """ SELECT loc_num FROM locations WHERE loc_name = %s; """
        cursor = mydb.cursor()
        cursor.execute(loc_num_query, (loc_name,))
        num_result = cursor.fetchone()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not num_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access locations reference tracking keys.",
                err_page_from="/",
            )
        loc_num = num_result[0]

    return render_template(
        "control_panel/cp_locdelconf.html",
        loc_name=loc_name,
        loc_num=loc_num,
    )



########################################################################
### EXECUTE LOCATION DELETION AND REASSIGN BOX DEPENDENCIES
@bp.route("/cp_locdelsuccess/<loc_name>", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error. Could not safely remove location or update dependent box records.")
def cp_locdelsuccess(loc_name):
    ### SAME PROTECTION AS cp_editloc/cp_delloc. This route deletes
    ### the row and can be POSTed to directly. Losing this row would
    ### break boxadded()'s fallback in boxes.py for boxes with no location.
    if loc_name == "Unspecified":
        return render_template(
            "errorpage.html",
            err_message='"Unspecified" is a protected location and cannot be deleted.',
            err_page_from="/control_panel/cp_locations",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 0. RESOLVE loc_num -- needed below since boxes.loc_num is
        ### the real foreign key, not the location name string.
        loc_num_query = """ SELECT loc_num FROM locations WHERE loc_name = %s """
        cursor = mydb.cursor()
        cursor.execute(loc_num_query, (loc_name,))
        num_result = cursor.fetchone()
        cursor.close()

        if not num_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access target location.",
                err_page_from="/",
            )
        loc_num = num_result[0]

        ### 1. REASSIGN BOXES MATCHING THIS LOCATION TO 'UNSPECIFIED'.
        ### Resolved by NAME rather than hardcoding loc_num 0 -- 0 is
        ### only guaranteed to be Unspecified's id on a fresh install
        ### (see deploy/schema.sql's seed data). Elsewhere, Unspecified's
        ### loc_num is whatever AUTO_INCREMENT assigned it, so hardcoding
        ### 0 could point at a loc_num that doesn't exist, raising the
        ### exact FK error this reassignment exists to avoid.
        ###
        ### boxes.loc_num is a real foreign key with ON DELETE RESTRICT
        ### (see deploy/schema.sql), so without this reassignment the
        ### delete below would bounce the person to a raw FK-constraint
        ### error instead of succeeding.
        cursor = mydb.cursor()
        unspecified_loc_num = get_or_create_loc_num(cursor, "Unspecified")
        cursor.close()

        update_box_loc_query = """ UPDATE boxes SET loc_num = %s WHERE loc_num = %s """
        cursor = mydb.cursor()
        cursor.execute(update_box_loc_query, (unspecified_loc_num, loc_num))
        cursor.close()

        ### 2. DELETE THE LOCATION MASTER RECORD
        del_loc_query = """ DELETE FROM locations WHERE loc_num = %s """
        cursor = mydb.cursor()
        cursor.execute(del_loc_query, (loc_num,))
        cursor.close()

    ### RETURN TO LOCATION LIST PAGE
    # The redirected route naturally fetches a fresh, updated locations dataset itself!
    return redirect(url_for("control_panel.cp_locations"))


########################################################################
### CONTROL PANEL VIEW DASHBOARD (COOKIES PASS-THROUGH)
@bp.route("/cp_view")
@login_required
def cp_view():
    ### READ THE COLUMN COOKIES (NO DATABASE HIT REQUIRED)
    info_column = request.cookies.get("info_column")
    photo_column = request.cookies.get("photo_column")
    date_column = request.cookies.get("date_column")
    cat_column = request.cookies.get("cat_column")
    box_column = request.cookies.get("box_column")

    ### CURRENT ITEMS-PER-PAGE SETTING (see extensions.get_items_per_page --
    ### falls back to DEFAULT_ITEMS_PER_PAGE/25 if no cookie is set yet,
    ### which is exactly the fresh-install case)
    items_per_page = get_items_per_page()

    return render_template(
        "control_panel/cp_view.html",
        info_column=info_column,
        photo_column=photo_column,
        date_column=date_column,
        cat_column=cat_column,
        box_column=box_column,
        items_per_page=items_per_page,
        allowed_items_per_page=ALLOWED_ITEMS_PER_PAGE,
    )


########################################################################
### DISPATCH PASSWORD CHANGE FORM
@bp.route("/cp_password")
@login_required
def cp_password():
    ### FRESH READ FROM DISK, NOT THE MODULE-LEVEL HASHED_IMPS_PASS
    # HASHED_IMPS_PASS (see extensions.py) is a one-way bcrypt hash --
    # there's no getting the plaintext back out of it. read_config()
    # re-reads imps_config.toml directly, the same way
    # setup.setup_password() already does, to get the actual current
    # plaintext value to pre-fill the form with.
    current_password = extensions.read_config().get("password", {}).get("password", "")

    return render_template(
        "control_panel/cp_password.html",
        current_password=current_password,
    )


########################################################################
### SUBMIT PASSWORD CHANGE
@bp.route("/cp_passwordedited", methods=["POST"])
@login_required
def cp_passwordedited():
    new_password = request.form.get("password", "")

    ### FRESH READ FROM DISK -- same reasoning as cp_password() above,
    ### and safer than trusting a client-supplied hidden field for
    ### "what the password used to be", since that field is just as
    ### editable as any other form input before it reaches us.
    current_password = extensions.read_config().get("password", {}).get("password", "")

    ### IF NOTHING ACTUALLY CHANGED, DO NOTHING -- matches the
    ### no-op-on-unchanged-submit behavior of setup.setup_password(),
    ### and avoids rewriting imps_config.toml (and rehashing
    ### HASHED_IMPS_PASS) for a change that isn't one.
    if new_password == current_password:
        return redirect(url_for("control_panel.controlpanel"))

    ### SERVER-SIDE MINIMUM LENGTH CHECK -- already enforced client-side
    ### in cp_password.html's JS; re-checked here since this route can
    ### be POSTed to directly without ever visiting that form.
    if len(new_password) < 4:
        return render_template(
            "errorpage.html",
            err_message="Password must be at least 4 characters.",
            err_page_from="/cp_password",
        )

    extensions.write_config_values("password", {"password": new_password})
    extensions.reload_config()

    return redirect(url_for("control_panel.controlpanel"))


