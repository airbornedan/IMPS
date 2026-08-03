########################################################################
### ITEMS BLUEPRINT — CREATE/EDIT/DELETE ITEMS
########################################################################
from flask import Blueprint, request, render_template, session, redirect, url_for
import os
import pathlib
import tempfile
import time
from datetime import date

from PIL import Image, ImageOps
from flask_paginate import Pagination, get_page_parameter
from werkzeug.utils import secure_filename

from app.extensions import (
    get_db_connection,
    login_required,
    validate_int,
    allowed_file,
    ITEM_IMAGE_DIR,
    ITEM_IMAGE_FS_DIR,
    limiter,
    verify_and_reencode_image,
    image_dir_size_bytes,
    MAX_IMAGE_DIR_BYTES,
    IMAGE_UPLOAD_LOCK,
    safe_relative_url,
    safe_image_path,
    logger,
    db_errors,
    run_query,
    get_items_per_page,
    get_offset_for_page,
    InvalidPageError,
    MAX_ITEM_NAME_LENGTH,
    MAX_ITEM_DESC_LENGTH,
    get_or_create_cat_num,
    touch_box_last_changed,
)

bp = Blueprint("items", __name__)

# items.cat_num is a numeric foreign key rather than a copy of the
# category name, so every items read needs categories joined in. Read
# sites fetch this with run_query(..., as_dict=True): each row comes
# back as a dict keyed by column/alias name (e.g. row['item_cat']),
# not a positional tuple, so column order doesn't need to match
# anything downstream by convention. c.cat_name is aliased to item_cat
# so the dict key matches the variable name every call site uses.
# Kept as one shared constant so read sites can't drift out of sync.
ITEMS_WITH_CAT_NAME = """
    SELECT i.item_num, i.item_name, i.box_num, i.item_pic, i.item_date,
           c.cat_name AS item_cat, i.item_desc
    FROM items i
    JOIN categories c ON i.cat_num = c.cat_num
"""


########################################################################
## ITEM DETAIL PAGE (NOT EDITABLE)
@bp.route("/itemdetail/<item_num>")
@login_required
@validate_int("item_num")
@db_errors(exec_msg="Database error when fetching item.")
def itemdetail(item_num):

    item_query = ITEMS_WITH_CAT_NAME + " WHERE item_num = %s "
    ### DB QUERY -- use the connection pool, same as every other route
    result = run_query(item_query, (item_num,), fetch="one", as_dict=True)

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Database error. Could not access item.",
            err_page_from="/",
        )

    ### SET UP VARIABLES TO SHOW ITEM DETAIL PAGE
    item_num = result["item_num"]
    item_name = result["item_name"]
    box_num = result["box_num"]
    item_pic = result["item_pic"]
    item_date = result["item_date"]
    item_cat = result["item_cat"]
    item_desc = result["item_desc"]

    ### "ADD ANOTHER" BUTTON -- shown only when ?from_add=1 is present.
    from_add = request.args.get("from_add") == "1"

    ### RETURN RESULTS PAGE
    return render_template(
        "items/itemdetail.html",
        item_name=item_name,
        item_num=item_num,
        item_pic=item_pic,
        box_num=box_num,
        item_date=item_date,
        item_cat=item_cat,
        item_desc=item_desc,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        from_add=from_add,
    )

########################################################################
### SHOW THE ADD ITEM FORM
@bp.route("/itemadd",  methods=["POST", "GET"])
@login_required
@db_errors(exec_msg="Database error when fetching form parameters.")
def itemadd():
    prov_box_num = 0
    if request.method == "POST":
        try:
            prov_box_num = int(request.form.get("prov_box_num", 0))
        except ValueError:
            prov_box_num = 0

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### SET UP QUERY FOR CATEGORIES
        category_query = "SELECT * FROM categories"
        cursor = mydb.cursor()
        cursor.execute(category_query)
        categories_result = cursor.fetchall()
        cursor.close()

        ### SET UP QUERY FOR AVAILABLE BOXES
        available_box_nums_query = "SELECT boxes.box_num FROM boxes;"
        cursor = mydb.cursor()
        cursor.execute(available_box_nums_query)
        boxes_result = cursor.fetchall()
        cursor.close()

    ### CONVERT RESULT TO CLEAN PYTHON DATA STRUCTURES
    available_categories = categories_result
    available_boxes = [row[0] for row in boxes_result]

    ### SHOW ITEM ADD PAGE
    return render_template(
        "items/itemadd.html",
        categories=available_categories,
        available_boxes=available_boxes,
        prov_box_num=prov_box_num
    )


########################################################################
### EDIT ITEM FORM
@bp.route("/itemedit/<item_num>")
@login_required
@validate_int("item_num")
@db_errors(exec_msg="Database error when retrieving data fields.")
def itemedit(item_num):
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### QUERY MAIN ITEM DETAILS
        item_query_statement = ITEMS_WITH_CAT_NAME + " WHERE item_num = %s "
        cursor = mydb.cursor(dictionary=True)
        cursor.execute(item_query_statement, (item_num,))
        item_result = cursor.fetchone()
        cursor.close()

        if not item_result:
            return render_template(
                "errorpage.html",
                err_message="Item number not in database.",
                err_page_from="/",
                )

        ### QUERY CATEGORY LIST
        category_query_statement = "SELECT * FROM categories;"
        cursor = mydb.cursor()
        cursor.execute(category_query_statement)
        categories_result = cursor.fetchall()
        cursor.close()

        ### QUERY FOR AVAILABLE BOXES
        available_box_nums_query = "SELECT boxes.box_num FROM boxes;"
        cursor = mydb.cursor()
        cursor.execute(available_box_nums_query)
        boxes_result = cursor.fetchall()
        cursor.close()

    ### ASSIGN RESULT VALUES
    item_num = item_result["item_num"]
    item_name = item_result["item_name"]
    box_num = item_result["box_num"]
    item_pic = item_result["item_pic"]
    item_date = item_result["item_date"]
    item_cat = item_result["item_cat"]
    item_desc = item_result["item_desc"]

    categories = categories_result
    
    ### EXTRACT AND SORT AVAILABLE BOXES
    available_boxes = [row[0] for row in boxes_result]
    available_boxes.sort()

    ### RETURN RESULTS PAGE
    return render_template(
        "items/itemedit.html",
        categories=categories,
        available_boxes=available_boxes,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        item_num=item_num,
        item_name=item_name,
        box_num=box_num,
        item_pic=item_pic,
        item_date=item_date,
        item_cat=item_cat,
        item_desc=item_desc,
    )


########################################################################
### SUBMIT EDITED ITEM DETAILS
@bp.route("/itemupdate/<item_num>", methods=["GET", "POST"])
@login_required
@validate_int("item_num")
@limiter.limit("30 per minute; 300 per hour")
@db_errors(exec_msg="Database write execution error. Changes could not be processed fully.")
def itemupdate(item_num):
    # Initialize response fallback values
    ud_item_name = ""
    ud_item_num = item_num
    ud_box_num = ""
    ud_item_date = ""
    ud_item_cat = ""
    ud_item_desc = ""
    item_pic = "none.jpg"

    ### IF A FORM HAS BEEN SUBMITTED, UPDATE ITEM INFO
    if request.method == "POST":
        ### GET FORM DATA
        ud_item_date = request.form.get("item_date")
        ud_item_name = request.form.get("item_name")
        ud_item_desc = request.form.get("item_desc")
        ud_box_num = request.form.get("box_num")
        ud_item_cat = request.form.get("item_cat")
        no_photo = request.form.get("no_photo")

        ### FORM DATA FROM HIDDEN FIELDS
        ud_passed_in_cat = request.form.get("passed_in_cat")
        ud_passed_in_pic = request.form.get("item_pic")
        item_pic = ud_passed_in_pic

        ### HANDLE CATEGORY DATAFIELD NOT CHANGED
        if not ud_item_cat:
            ud_item_cat = ud_passed_in_cat

        ### VALIDATE ITEM NAME LENGTH -- before any DB write or photo
        ### processing below, so a too-long name is rejected up front
        ### rather than after other work's done. UI enforces this via
        ### maxlength="50" + JS (see itemedit.html), client-side only
        ### -- a direct POST bypasses it, so it's checked here too.
        if ud_item_name and len(ud_item_name) > MAX_ITEM_NAME_LENGTH:
            return render_template(
                "errorpage.html",
                err_message=(
                    f"Item names are limited to {MAX_ITEM_NAME_LENGTH} characters. "
                    "Use the description field to store more information about this item."
                ),
                err_page_from=f"/itemedit/{item_num}",
            )

        ### VALIDATE ITEM DESCRIPTION LENGTH, SAME REASONING -- UI
        ### enforces this via maxlength + JS (see itemedit.html),
        ### client-side only -- a direct POST bypasses it, so it's
        ### checked here too.
        if ud_item_desc and len(ud_item_desc) > MAX_ITEM_DESC_LENGTH:
            return render_template(
                "errorpage.html",
                err_message=f"Item descriptions are limited to {MAX_ITEM_DESC_LENGTH} characters.",
                err_page_from=f"/itemedit/{item_num}",
            )

        # Fetch an active, thread-safe connection from the pool
        with get_db_connection() as mydb:
            ### 1. RESOLVE THE SUBMITTED CATEGORY NAME TO ITS cat_num,
            ### CREATING THE CATEGORY IF IT'S A BRAND NEW NAME. See
            ### get_or_create_cat_num() in extensions.py.
            cursor = mydb.cursor()
            ud_cat_num = get_or_create_cat_num(cursor, ud_item_cat)
            cursor.close()

            ### 1b. READ THE ITEM'S CURRENT box_num, BEFORE THE UPDATE
            ### OVERWRITES IT -- needed below (step 2b) to tell whether
            ### this edit moved the item to a different box.
            ### box_last_changed only gets touched on a real move, not
            ### a same-box name/desc/category/photo edit. Cast to int
            ### (this column comes back as an int; ud_box_num is a raw
            ### form value) for a real integer comparison, invalid-safe.
            cursor = mydb.cursor()
            cursor.execute("SELECT box_num FROM items WHERE item_num = %s", (ud_item_num,))
            previous_box_row = cursor.fetchone()
            cursor.close()
            previous_box_num = previous_box_row[0] if previous_box_row else None

            try:
                ud_box_num_int = int(ud_box_num)
            except (TypeError, ValueError):
                ud_box_num_int = None

            ### 2. WRITE CORE ITEM VALUES TO DB
            item_update_query = """ UPDATE items SET item_name = %s, item_desc = %s, cat_num = %s,\
                item_date = %s, box_num = %s WHERE item_num = %s """
            
            cursor = mydb.cursor()
            cursor.execute(
                item_update_query,
                (
                    ud_item_name,
                    ud_item_desc,
                    ud_cat_num,
                    ud_item_date,
                    ud_box_num,
                    ud_item_num,
                ),
            )
            cursor.close()

            ### 2b. IF THE ITEM MOVED TO A DIFFERENT BOX, TOUCH BOTH THE
            ### OLD AND NEW BOX -- something left one, arrived in the
            ### other. A same-box edit doesn't count, so this is
            ### skipped entirely then. See touch_box_last_changed() in
            ### extensions.py.
            if previous_box_num != ud_box_num_int:
                cursor = mydb.cursor()
                touch_box_last_changed(cursor, previous_box_num)
                touch_box_last_changed(cursor, ud_box_num_int)
                cursor.close()

            ####################################################
            ### IMAGE HANDLING (FILESYSTEM OPERATIONS)
            ####################################################
            file = request.files.get("file")

            ### IF A FILE IS SUBMITTED BUT THE TYPE IS PROHIBITED
            if file and file.filename != "" and not allowed_file(file.filename):
                return render_template(
                    "errorpage.html",
                    err_message="That file type is not allowed.",
                    err_page_from="/",
                )

            ### IF THE FILE IS VALID, PROCESS AND SAVE IT
            if file and file.filename != "" and allowed_file(file.filename):
                ### SIZE-CAP CHECK + SAVE, SERIALIZED -- see
                ### IMAGE_UPLOAD_LOCK in extensions.py. Held from the
                ### size check through the initial save so the two
                ### steps are atomic with respect to other concurrent
                ### uploads; verify/re-encode/thumbnail below don't
                ### grow the directory further, so they run outside
                ### the lock.
                with IMAGE_UPLOAD_LOCK:
                    ### REJECT IF THE IMAGE DIRECTORY IS ALREADY AT ITS SIZE CAP
                    if image_dir_size_bytes(ITEM_IMAGE_FS_DIR) >= MAX_IMAGE_DIR_BYTES:
                        return render_template(
                            "errorpage.html",
                            err_message="Storage is full for this demo instance. Please try again after the next scheduled reset.",
                            err_page_from="/",
                        )

                    filename = secure_filename(file.filename)

                    ### ADD TIMESTAMP TO FILE NAME TO HANDLE DUPES
                    pp = pathlib.PurePath(filename)
                    filename = pp.stem + str(time.time()) + pp.suffix
                    save_path = os.path.join(ITEM_IMAGE_FS_DIR, filename)

                    ### SAVE THE UPLOAD TO A TEMP FILE, NOT THE FINAL PATH
                    ### -- an unverified upload never lands in the
                    ### directory IMPS serves images from, even briefly.
                    temp_fd, temp_path = tempfile.mkstemp(
                        dir=ITEM_IMAGE_FS_DIR, prefix=".upload_", suffix=pp.suffix
                    )
                    os.close(temp_fd)
                    file.save(temp_path)

                ### VERIFY THE UPLOADED BYTES ARE ACTUALLY A DECODABLE
                ### IMAGE AND RE-ENCODE, DISCARDING THE ORIGINAL BYTES.
                if not verify_and_reencode_image(temp_path):
                    return render_template(
                        "errorpage.html",
                        err_message="That file could not be processed as a valid image.",
                        err_page_from="/",
                    )

                ### SHRINK IMAGE TO A REASONABLE SIZE AND SAVE
                image = Image.open(temp_path)
                image = ImageOps.exif_transpose(image)
                image.thumbnail((600, 600))
                image.save(temp_path)

                ### MOVE THE FULLY VERIFIED AND PROCESSED IMAGE INTO PLACE
                os.replace(temp_path, save_path)

                ### DELETE FORMER PHOTO UNLESS IT IS THE PLACEHOLDER
                # ud_passed_in_pic comes from a hidden form field, so
                # it's attacker-controlled -- run it through
                # safe_image_path() rather than concatenating it into
                # a path directly, or a crafted value like
                # "../../../../etc/passwd" gets handed to os.remove().
                if ud_passed_in_pic != "none.jpg":
                    photo_to_delete = safe_image_path(
                        ud_passed_in_pic, ITEM_IMAGE_FS_DIR
                    )
                    if photo_to_delete:
                        try:
                            os.remove(photo_to_delete)
                        except FileNotFoundError:
                            pass
                        except Exception as e:
                            logger.warning(f"itemupdate(): could not delete old photo {photo_to_delete!r}: {e}")

                item_pic = filename

            ### IF NO PHOTO CHECKBOX IS SELECTED RESET IMAGE TO DEFAULT
            if no_photo:
                item_pic = "none.jpg"

                ### ATTEMPT TO DELETE OLD PHOTO
                # Same reasoning as above -- sanitize before removing.
                if ud_passed_in_pic != "none.jpg":
                    photo_to_delete = safe_image_path(
                        ud_passed_in_pic, ITEM_IMAGE_FS_DIR
                    )
                    if photo_to_delete:
                        try:
                            os.remove(photo_to_delete)
                        except FileNotFoundError:
                            pass
                        except Exception as e:
                            logger.warning(f"itemupdate(): could not delete old photo {photo_to_delete!r}: {e}")

            ### 3. UPDATE FINAL FILENAME ENTRY IN DATABASE
            pic_query = """ UPDATE items SET item_pic = %s WHERE item_num = %s """
            cursor = mydb.cursor()
            cursor.execute(pic_query, (item_pic, item_num))
            cursor.close()

            ### 4. GET CONFIRMED ITEM PIC FROM DATABASE TO DISPLAY ON RESULTS PAGE
            item_query = """ SELECT item_pic FROM items WHERE item_num = %s """
            cursor = mydb.cursor()
            cursor.execute(item_query, (item_num,))
            result = cursor.fetchone()
            cursor.close()

            if result:
                item_pic = result[0]

    ### REDIRECT TO THE ITEM DETAIL PAGE
    return redirect(url_for("items.itemdetail", item_num=ud_item_num))

########################################################################
### ADD ITEM TO DB AND UPLOAD AND SAVE PHOTO
@bp.route("/iteminsert", methods=["POST"])
@login_required
# IMPS write access is intentionally open (public demo password), so
# unlike login this isn't guarding a secret -- it's guarding against a
# script hammering item creation between resets.
@limiter.limit("30 per minute; 300 per hour")
@db_errors(exec_msg="Database error. Could not complete data insertion.")
def iteminsert():
    ### VALIDATE ITEM NAME LENGTH UP FRONT -- before any photo
    ### processing below, so a too-long name is rejected immediately
    ### rather than after an upload's already been saved/resized for
    ### nothing. UI enforces this via maxlength="50" + JS (see
    ### itemadd.html), client-side only -- a direct POST bypasses it,
    ### so it's checked here too.
    item_name = request.form.get("item_name") or ""
    if not item_name.strip():
        return render_template(
            "errorpage.html",
            err_message="Item name cannot be blank.",
            err_page_from="/itemadd",
        )
    if len(item_name) > MAX_ITEM_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=(
                f"Item names are limited to {MAX_ITEM_NAME_LENGTH} characters. "
                "Use the description field to store more information about this item."
            ),
            err_page_from="/itemadd",
        )

    ### VALIDATE ITEM DESCRIPTION LENGTH UP FRONT, SAME REASONING -- UI
    ### enforces this via maxlength + JS (see itemadd.html), client-side
    ### only -- a direct POST bypasses it, so it's checked here too.
    item_desc_precheck = request.form.get("item_desc") or ""
    if len(item_desc_precheck) > MAX_ITEM_DESC_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=f"Item descriptions are limited to {MAX_ITEM_DESC_LENGTH} characters.",
            err_page_from="/itemadd",
        )

    ### photo_yes_no IS A "yes"/"no" RADIO GROUP (see itemadd.html)
    photo_included = request.form.get("photo_yes_no") == "yes"

    if photo_included:
        ### CHECK THAT THE POST CONTAINS FILE DATA
        if "file" not in request.files:
            return render_template(
                "errorpage.html",
                err_message="The photo did not load.",
                err_page_from="/itemadd",
            )

        file = request.files["file"]
        ### HANDLE CASE WHERE BROWSER SUBMITS A FILE WITHOUT A NAME
        if file.filename == "":
            return render_template(
                "errorpage.html",
                err_message="No file selected",
                err_page_from="/itemadd",
            )

        ### SIZE-CAP CHECK + SAVE, SERIALIZED -- see IMAGE_UPLOAD_LOCK in
        ### extensions.py. Held from the size check through the initial
        ### save so the two steps are atomic with respect to other
        ### concurrent uploads; verify/re-encode/thumbnail below don't
        ### grow the directory further, so they run outside the lock.
        with IMAGE_UPLOAD_LOCK:
            ### REJECT IF THE IMAGE DIRECTORY IS ALREADY AT ITS SIZE CAP
            if image_dir_size_bytes(ITEM_IMAGE_FS_DIR) >= MAX_IMAGE_DIR_BYTES:
                return render_template(
                    "errorpage.html",
                    err_message="Storage is full for this demo instance. Please try again after the next scheduled reset.",
                    err_page_from="/itemadd",
                )

            ### IF THE FILE IS ALLOWED AND IN THE POST, SAVE IT
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)

                ### TIMESTAMP THE FILENAME TO HANDLE DUPES
                pp = pathlib.PurePath(filename)
                filename = pp.stem + str(time.time()) + pp.suffix
                save_path = os.path.join(ITEM_IMAGE_FS_DIR, filename)

                ### SAVE THE UPLOAD TO A TEMP FILE, NOT THE FINAL PATH
                ### -- an unverified upload never lands in the
                ### directory IMPS serves images from, even briefly.
                temp_fd, temp_path = tempfile.mkstemp(
                    dir=ITEM_IMAGE_FS_DIR, prefix=".upload_", suffix=pp.suffix
                )
                os.close(temp_fd)
                file.save(temp_path)

            ### IF THE FILE IS PROHIBITED SHOW ERROR PAGE
            else:
                return render_template(
                    "errorpage.html",
                    err_message="That file type is not allowed.",
                    err_page_from="/itemadd",
                )

        ### VERIFY THE UPLOADED BYTES ARE ACTUALLY A DECODABLE IMAGE
        ### AND RE-ENCODE, DISCARDING THE ORIGINAL FILE CONTENT. THIS
        ### IS THE REAL CONTENT-LEVEL CHECK -- allowed_file() ABOVE
        ### ONLY LOOKED AT THE FILENAME, NOT THE BYTES.
        if not verify_and_reencode_image(temp_path):
            return render_template(
                "errorpage.html",
                err_message="That file could not be processed as a valid image.",
                err_page_from="/itemadd",
            )

        # SHRINK IMAGE
        image = Image.open(temp_path)
        image = ImageOps.exif_transpose(image)
        image.thumbnail((600, 600))
        image.save(temp_path)

        ### MOVE THE FULLY VERIFIED AND PROCESSED IMAGE INTO PLACE
        os.replace(temp_path, save_path)
    ### IF NO FILE WAS INCLUDED USE THE DEFAULT PHOTO
    else:
        filename = ""

    ### GET DATE SO WE CAN SET ITEM DATE
    current_date = str(date.today())

    ### GET FORM DATA FOR INSERTION INTO DATABASE
    ### (item_name was already fetched and length-checked at the top
    ### of this function, before photo processing)
    box_num = request.form.get("box_num")
    item_cat = request.form.get("item_cat")
    item_desc = request.form.get("item_desc")

    ### IF NO CATEGORY SELECTED, USE UNCATEGORIZED
    if not item_cat or item_cat == "":
        item_cat = "Uncategorized"

    ### IF NO FILE SELECTED, USE DEFAULT "NONE.JPG"
    item_pic = filename if filename != "" else "none.jpg"

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. RESOLVE THE SUBMITTED CATEGORY NAME TO ITS cat_num,
        ### CREATING THE CATEGORY IF IT'S A BRAND NEW NAME -- relies on
        ### the cat_name UNIQUE constraint plus a caught IntegrityError
        ### rather than a SELECT-then-check-then-INSERT, which would be
        ### a race condition (two concurrent requests could both pass
        ### the check before either INSERT lands, producing duplicate
        ### rows). See get_or_create_cat_num() in extensions.py.
        cursor = mydb.cursor()
        cat_num = get_or_create_cat_num(cursor, item_cat)
        cursor.close()

        ### 2. INSERT NEW ITEM INTO DATABASE
        insert_query = """ INSERT INTO items (item_name, box_num, item_pic, item_date, cat_num, item_desc) \
             VALUES (%s, %s, %s, %s, %s, %s) """
    
        cursor = mydb.cursor()
        cursor.execute(
            insert_query,
            (item_name, box_num, item_pic, current_date, cat_num, item_desc),
        )
        cursor.close()

        ### 2b. TOUCH THE BOX -- an item was just added to it. See
        ### touch_box_last_changed() in extensions.py.
        cursor = mydb.cursor()
        touch_box_last_changed(cursor, box_num)
        cursor.close()

        ### 3. GET THE ITEM NUMBER OF THE ITEM ADDED
        last_item_query = "SELECT LAST_INSERT_ID();"
        cursor = mydb.cursor()
        cursor.execute(last_item_query)
        result = cursor.fetchone()
        cursor.close()

        if not result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access last inserted item reference ID.",
                err_page_from="/",
            )
        item_num = result[0]

    ### REDIRECT TO THE ITEM DETAIL PAGE
    return redirect(url_for("items.itemdetail", item_num=item_num, from_add="1"))







########################################################################
### SHOW ALL ITEMS IN A CATEGORY
@bp.route("/itemsbycategory/<category>")
@login_required
@db_errors(exec_msg="Database error when fetching categorized item grids.")
def itemsbycategory(category):
    #####################################
    ############# PAGINATION
    limit = get_items_per_page()
    try:
        offset = get_offset_for_page(limit)
    except InvalidPageError:
        return render_template(
            "errorpage.html",
            err_message="That page number doesn't exist.",
            err_page_from="/bycategory",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### QUERY FOR ITEMS IN CATEGORY
        item_by_cat_query = (
            ITEMS_WITH_CAT_NAME
            + " WHERE c.cat_name = %s ORDER BY i.item_num DESC LIMIT %s OFFSET %s "
        )
        cursor = mydb.cursor(dictionary=True)
        cursor.execute(item_by_cat_query, (category, limit, offset))
        result = cursor.fetchall()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not result:
            return render_template(
                "errorpage.html",
                err_message="There are no items in this category or this category does not exist.",
                err_page_from="/bycategory",
            )
        item_list = result

        ### QUERY FOR NUMBER OF ITEMS IN CATEGORY
        count_query = """ SELECT COUNT(*) FROM items i
                           JOIN categories c ON i.cat_num = c.cat_num
                           WHERE c.cat_name = %s """
        cursor = mydb.cursor()
        cursor.execute(count_query, (category,))
        count_result = cursor.fetchone()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not count_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access categories.",
                err_page_from="/",
            )
        total = int(count_result[0])

    #####################################
    ############# PAGINATION
    page = request.args.get(get_page_parameter(), type=int, default=1)
    pagination = Pagination(
        page=page,
        total=total,
        per_page=limit,
    )

    ### READ THE COLUMN COOKIES
    info_column = request.cookies.get("info_column")
    photo_column = request.cookies.get("photo_column")
    date_column = request.cookies.get("date_column")
    cat_column = request.cookies.get("cat_column")
    box_column = request.cookies.get("box_column")

    ### GET COOKIE AND SHOW THE APPROPRIATE VIEW
    ### (itemsbycat.html branches internally on current_view)
    current_view = request.cookies.get("view")
    return render_template(
        "items/itemsbycat.html",
        current_view=current_view,
        item_list=item_list,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        cat_name=category,
        page=page,
        pagination=pagination,
        info_column=info_column,
        photo_column=photo_column,
        date_column=date_column,
        cat_column=cat_column,
        box_column=box_column,
    )


########################################################################
## DELETE ITEM CONFIRMATION PAGE
@bp.route("/itemdel/<item_num>")
@login_required
@validate_int("item_num")
@db_errors(exec_msg="Database error when fetching item deletion metrics.")
def itemdel(item_num):
    # Fetch an active, thread-safe connection from the pool
    del_query = ITEMS_WITH_CAT_NAME + " WHERE item_num = %s "
    result = run_query(del_query, (item_num,), fetch="one", as_dict=True)

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Item number not in database.",
            err_page_from="/",
        )

    ### SET VARIABLES NEEDED FOR PAGE DISPLAY FROM RESULT DICT
    item_num = result["item_num"]
    item_name = result["item_name"]
    box_num = result["box_num"]
    item_pic = result["item_pic"]
    item_date = result["item_date"]
    item_cat = result["item_cat"]
    item_desc = result["item_desc"]

    ### PULL WHERE THE USER CAME FROM OUT OF THE SESSION (see
    ### LIST_VIEW_ENDPOINTS / remember_list_view in app/__init__.py) SO
    ### THE POST-DELETE SUCCESS PAGE CAN OFFER A WAY BACK TO IT. Doesn't
    ### rely on the browser's Referer header, which proxies, CDNs, and
    ### privacy settings can strip unpredictably. Sanitized here AND
    ### again in itemdeleted() before being rendered as a link -- never
    ### trust it as a redirect target without checking.
    back_url = safe_relative_url(session.get("last_list_view"))

    ### RETURN RESULTS PAGE
    return render_template(
        "items/itemdel.html",
        item_num=item_num,
        item_name=item_name,
        box_num=box_num,
        item_pic=item_pic,
        item_date=item_date,
        item_cat=item_cat,
        item_desc=item_desc,
        back_url=back_url,
    )


########################################################################
@bp.route("/itemdeleted/<item_to_del>", methods=["POST"])
@login_required
@validate_int("item_to_del")
@db_errors(exec_msg="Database write execution error. Could not delete item safely.")
def itemdeleted(item_to_del):
    ### RE-VALIDATE THE BACK URL HERE TOO -- IT ARRIVED AS A POST BODY
    ### FIELD FROM THE CLIENT, SO TREAT IT AS UNTRUSTED EVEN THOUGH
    ### itemdel() ALREADY SANITIZED IT ONCE.
    back_url = safe_relative_url(request.form.get("back_url"))

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. GET PHOTO FILE NAME FROM DB
        photo_file_query = """ SELECT item_pic FROM items WHERE item_num = %s """
        cursor = mydb.cursor()
        cursor.execute(photo_file_query, (item_to_del,))
        photo_result = cursor.fetchone()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not photo_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access photos.",
                err_page_from="/",
            )
        photo_filename = photo_result[0]

        ### 2. GET ITEM NAME AND BOX NUMBER FOR RESULTS PAGE / BOX-TOUCH
        ### BEFORE DELETION -- box_num is needed to mark the box as
        ### touched below (step 3b); once the row's deleted, it's gone.
        item_name_query = """ SELECT item_name, box_num FROM items WHERE item_num = %s """
        cursor = mydb.cursor()
        cursor.execute(item_name_query, (item_to_del,))
        name_result = cursor.fetchone()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not name_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access item.",
                err_page_from="/",
            )
        item_name = name_result[0]
        box_num = name_result[1]

        ### 3. EXECUTE DELETION STATEMENT
        del_query = """ DELETE FROM items WHERE item_num = %s """
        cursor = mydb.cursor()
        cursor.execute(del_query, (item_to_del,))
        cursor.close()

        ### 3b. TOUCH THE BOX -- an item was just removed from it. See
        ### touch_box_last_changed() in extensions.py.
        cursor = mydb.cursor()
        touch_box_last_changed(cursor, box_num)
        cursor.close()

    ### PROCESS FILESYSTEM OPERATIONS OUTSIDE DATABASE LOCKS
    photo_dir = ITEM_IMAGE_FS_DIR
    delete_failed = False

    ### ATTEMPT TO DELETE THE PHOTO UNLESS THERE'S NO REAL IMAGE TO DELETE.
    ### "No real image" covers the placeholder ("none.jpg") and
    ### NULL/empty item_pic values from older or imported data -- none
    ### represent an actual file on disk, so nothing to attempt.
    has_real_photo = bool(photo_filename) and photo_filename != "none.jpg"

    if has_real_photo:
        ### photo_filename comes from the DB, not the request, but
        ### treat it as untrusted: run it through safe_image_path()
        ### (itemupdate() above, cp_photofilesdel() in
        ### control_panel.py).
        photo_file = safe_image_path(photo_filename, photo_dir)
        if photo_file is None:
            logger.error(
                f"itemdeleted(): refusing to delete unsafe/invalid "
                f"photo filename from DB: {photo_filename!r}"
            )
            photo_file = os.path.join(photo_dir, "__nonexistent__")
        try:
            os.remove(photo_file)
        except FileNotFoundError:
            # Best effort file removal. File already gone (cleaned up
            # by the orphan-photos tool, or removed by hand) is fine --
            # the end state we wanted is already true. Not a real
            # failure; only genuine errors (permissions, I/O) below.
            pass
        except OSError as file_error:
            logger.error(f"System File deletion error: {file_error}")
            delete_failed = True

    ### RETURN SUCCESS OR WARN ABOUT ORPHANED IMAGE FILE
    if delete_failed:
        return render_template(
            "errorpage.html",
            err_message="The item was deleted from the database, but IMPS was unable to delete the image file.",
            err_page_from="/",
        )
    else:
        return render_template(
            "items/itemdelconfirm.html",
            item_name=item_name,
            back_url=back_url,
            had_photo=has_real_photo,
        )
