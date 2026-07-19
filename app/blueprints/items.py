########################################################################
### ITEMS BLUEPRINT — CREATE/EDIT/DELETE ITEMS
########################################################################
from flask import Blueprint, request, render_template, redirect, url_for, make_response, session
import os
import pathlib
import time
from datetime import date

from PIL import Image, ImageOps
from flask_paginate import Pagination, get_page_parameter
from werkzeug.utils import secure_filename

from mysql.connector.errors import IntegrityError

from app.extensions import (
    get_db_connection,
    DBConnectionError,
    login_required,
    allowed_file,
    ITEM_IMAGE_DIR,
    ITEM_IMAGE_FS_DIR,
    limiter,
    verify_and_reencode_image,
    image_dir_size_bytes,
    MAX_IMAGE_DIR_BYTES,
    safe_relative_url,
    safe_image_path,
    logger,
    db_errors,
    run_query,
    get_items_per_page,
    get_offset_for_page,
    InvalidPageError,
    MAX_ITEM_NAME_LENGTH,
)

bp = Blueprint("items", __name__)


@bp.route("/itemdetails/<item_num>")
@login_required
@db_errors(exec_msg="Database error when fetching item properties.")
def itemdetails(item_num):
    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    item_query_statement = """ SELECT * FROM items WHERE item_num = %s """
    result = run_query(item_query_statement, (item_num,), fetch="one")

    if not result:
        return render_template(
            "errorpage.html",
            err_message="Database error. Could not access item.",
            err_page_from="/",
        )

    # Deconstruct properties explicitly out of the isolated result tuple
    item_num = result[0]
    item_name = result[1]
    box_num = result[2]
    item_pic = result[3]
    item_date = result[4]
    item_cat = result[5]
    item_desc = result[6]

    return render_template(
        "items/itemdetail.html",
        item_num=item_num,
        item_name=item_name,
        box_num=box_num,
        item_pic=item_pic,
        item_date=item_date,
        item_cat=item_cat,
        item_desc=item_desc,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
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
@db_errors(exec_msg="Database error when retrieving data fields.")
def itemedit(item_num):
    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### QUERY MAIN ITEM DETAILS
        item_query_statement = """ SELECT * FROM items WHERE item_num = %s """
        cursor = mydb.cursor()
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
    item_num = item_result[0]
    item_name = item_result[1]
    box_num = item_result[2]
    item_pic = item_result[3]
    item_date = item_result[4]
    item_cat = item_result[5]
    item_desc = item_result[6]

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
@bp.route("/updateitem/<item_num>", methods=["GET", "POST"])
@login_required
@limiter.limit("30 per minute; 300 per hour")
@db_errors(exec_msg="Database write execution error. Changes could not be processed fully.")
def updateitem(item_num):
    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    # Initialize response fallback values
    ud_item_name = ""
    ud_item_num = item_num
    ud_box_num = ""
    ud_item_date = ""
    ud_item_cat = ""
    ud_item_desc = ""
    photo_message = "Original photo retained."
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
        ### rather than after other work's already been done. The UI
        ### already enforces this via maxlength="50" + JS (see
        ### itemedit.html), but that's client-side only -- a direct
        ### POST bypasses it entirely, so it has to be checked here too.
        if ud_item_name and len(ud_item_name) > MAX_ITEM_NAME_LENGTH:
            return render_template(
                "errorpage.html",
                err_message=(
                    f"Item names are limited to {MAX_ITEM_NAME_LENGTH} characters. "
                    "Use the description field to store more information about this item."
                ),
                err_page_from=f"/itemedit/{item_num}",
            )

        # Fetch an active, thread-safe connection from the pool
        with get_db_connection() as mydb:
            ### 1. WRITE CORE ITEM VALUES TO DB
            item_update_query = """ UPDATE items SET item_name = %s, item_desc = %s, item_cat = %s,\
                item_date = %s, box_num = %s WHERE item_num = %s """
            
            cursor = mydb.cursor()
            cursor.execute(
                item_update_query,
                (
                    ud_item_name,
                    ud_item_desc,
                    ud_item_cat,
                    ud_item_date,
                    ud_box_num,
                    ud_item_num,
                ),
            )
            cursor.close()

            ### 2. ENSURE THE CATEGORY EXISTS. Relies on the cat_name
            ### UNIQUE constraint: attempts the insert, and a
            ### duplicate-key error simply means the category already
            ### exists.
            add_cat_query = """ INSERT INTO categories (cat_name) VALUES (%s) """
            cursor = mydb.cursor()
            try:
                cursor.execute(add_cat_query, (ud_item_cat,))
            except IntegrityError:
                pass  # category already exists -- nothing to do
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
                ### REJECT IF THE IMAGE DIRECTORY IS ALREADY AT ITS SIZE CAP
                if image_dir_size_bytes(ITEM_IMAGE_FS_DIR) >= MAX_IMAGE_DIR_BYTES:
                    return render_template(
                        "errorpage.html",
                        err_message="Storage is full for this demo instance. Please try again after the next scheduled reset.",
                        err_page_from="/",
                    )

                filename = secure_filename(file.filename)
                photo_message = "Photo updated."

                ### ADD TIMESTAMP TO FILE NAME TO HANDLE DUPES
                pp = pathlib.PurePath(filename)
                filename = pp.stem + str(time.time()) + pp.suffix
                save_path = os.path.join(ITEM_IMAGE_FS_DIR, filename)

                ### SAVE FILE
                file.save(save_path)

                ### VERIFY THE UPLOADED BYTES ARE ACTUALLY A DECODABLE
                ### IMAGE AND RE-ENCODE, DISCARDING THE ORIGINAL BYTES.
                if not verify_and_reencode_image(save_path):
                    return render_template(
                        "errorpage.html",
                        err_message="That file could not be processed as a valid image.",
                        err_page_from="/",
                    )

                ### SHRINK IMAGE TO A REASONABLE SIZE AND SAVE
                image = Image.open(save_path)
                image = ImageOps.exif_transpose(image)
                image.thumbnail((600, 600))
                image.save(save_path)

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
                        except Exception:
                            pass

                item_pic = filename

            ### IF NO PHOTO CHECKBOX IS SELECTED RESET IMAGE TO DEFAULT
            if no_photo:
                item_pic = "none.jpg"
                photo_message = "Photo removed."

                ### ATTEMPT TO DELETE OLD PHOTO
                # Same reasoning as above -- sanitize before removing.
                if ud_passed_in_pic != "none.jpg":
                    photo_to_delete = safe_image_path(
                        ud_passed_in_pic, ITEM_IMAGE_FS_DIR
                    )
                    if photo_to_delete:
                        try:
                            os.remove(photo_to_delete)
                        except Exception:
                            pass

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

    ### SHOW ITEM PAGE
    return render_template(
        "items/itemdetail.html",
        item_name=ud_item_name,
        item_num=ud_item_num,
        box_num=ud_box_num,
        item_date=ud_item_date,
        item_cat=ud_item_cat,
        item_desc=ud_item_desc,
        item_pic=item_pic,
        photo_message=photo_message,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
    )

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
    ### nothing. The UI already enforces this via maxlength="50" +
    ### JS (see itemadd.html), but that's client-side only -- a direct
    ### POST bypasses it entirely, so it has to be checked here too.
    item_name = request.form.get("item_name") or ""
    if len(item_name) > MAX_ITEM_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=(
                f"Item names are limited to {MAX_ITEM_NAME_LENGTH} characters. "
                "Use the description field to store more information about this item."
            ),
            err_page_from="/itemadd",
        )

    photoincluded = request.form.get("photo_yes_no")

    if photoincluded == "yes":
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
            file.save(save_path)

            ### VERIFY THE UPLOADED BYTES ARE ACTUALLY A DECODABLE IMAGE
            ### AND RE-ENCODE, DISCARDING THE ORIGINAL FILE CONTENT. THIS
            ### IS THE REAL CONTENT-LEVEL CHECK -- allowed_file() ABOVE
            ### ONLY LOOKED AT THE FILENAME, NOT THE BYTES.
            if not verify_and_reencode_image(save_path):
                return render_template(
                    "errorpage.html",
                    err_message="That file could not be processed as a valid image.",
                    err_page_from="/itemadd",
                )

            # SHRINK IMAGE
            image = Image.open(save_path)
            image = ImageOps.exif_transpose(image)
            image.thumbnail((600, 600))
            image.save(save_path)

        ### IF THE FILE IS PROHIBITED SHOW ERROR PAGE
        else:
            return render_template(
                "errorpage.html",
                err_message="That file type is not allowed.",
                err_page_from="/itemadd",
            )
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
        ### 1. INSERT NEW ITEM INTO DATABASE
        insert_query = """ INSERT INTO items (item_name, box_num, item_pic, item_date, item_cat, item_desc) \
             VALUES (%s, %s, %s, %s, %s, %s) """
    
        cursor = mydb.cursor()
        cursor.execute(
            insert_query,
            (item_name, box_num, item_pic, current_date, item_cat, item_desc),
        )
        cursor.close()

        ### 2. GET THE ITEM NUMBER OF THE ITEM ADDED
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

        ### 3. ENSURE THE CATEGORY EXISTS -- relies on the cat_name
        ### UNIQUE constraint plus a caught IntegrityError, rather than
        ### a SELECT-then-check-then-INSERT, which would be a race
        ### condition (two concurrent requests could both pass the
        ### check before either INSERT lands, producing duplicate rows).
        add_cat_query = """ INSERT INTO categories (cat_name) VALUES (%s) """
        cursor = mydb.cursor()
        try:
            cursor.execute(add_cat_query, (item_cat,))
        except IntegrityError:
            pass  # category already exists -- nothing to do
        cursor.close()

    ### SHOW THE RESULTS PAGE
    return showitemdetail(str(item_num))






########################################################################
## ITEM DETAIL PAGE (NOT EDITABLE)
@bp.route("/showitemdetail/<item_num>")
@login_required
@db_errors(exec_msg="Database error when fetching item.")
def showitemdetail(item_num):

    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    item_query = """ SELECT * FROM items WHERE item_num = %s """
    ### DB QUERY -- use the connection pool, same as every other route
    result = run_query(item_query, (item_num,), fetch="one")

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Database error. Could not access item.",
            err_page_from="/",
        )
    item_result = result

    ### SET UP VARIABLES TO SHOW ITEM DETAIL PAGE
    item_num = item_result[0]
    item_name = item_result[1]
    box_num = item_result[2]
    item_pic = item_result[3]
    item_date = item_result[4]
    item_cat = item_result[5]
    item_desc = item_result[6]

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
        from_add=True,
    )



########################################################################
### SHOW ALL ITEMS IN A CATEGORY
@bp.route("/itemsbycategory/<category>")
@login_required
@db_errors(exec_msg="Database error when fetching categorized item grids.")
def itembycategory(category):
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
        item_by_cat_query = """ SELECT * FROM items WHERE item_cat = %s ORDER BY item_num DESC LIMIT %s OFFSET %s """
        cursor = mydb.cursor()
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
        count_query = """ SELECT COUNT(*) FROM items WHERE item_cat = %s """
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
    search = False
    q = request.args.get("q")
    if q:
        search = True

    page = request.args.get(get_page_parameter(), type=int, default=1)
    pagination = Pagination(
        page=page,
        total=total,
        search=search,
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
@db_errors(exec_msg="Database error when fetching item deletion metrics.")
def itemdel(item_num):
    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    del_query = """ SELECT * FROM items WHERE item_num = %s """
    result = run_query(del_query, (item_num,), fetch="one")

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Item number not in database.",
            err_page_from="/",
        )

    ### SET VARIABLES NEEDED FOR PAGE DISPLAY FROM UNCOUPLED TUPLE
    item_num = result[0]
    item_name = result[1]
    box_num = result[2]
    item_pic = result[3]
    item_date = result[4]
    item_cat = result[5]
    item_desc = result[6]

    ### PULL WHERE THE USER CAME FROM OUT OF THE SESSION (see
    ### LIST_VIEW_ENDPOINTS / remember_list_view in app/__init__.py) SO
    ### THE POST-DELETE SUCCESS PAGE CAN OFFER A WAY BACK TO IT. This
    ### doesn't rely on the browser's Referer header, which proxies,
    ### CDNs, and privacy settings can strip unpredictably. Sanitized
    ### here AND again in itemdeleted() before ever being rendered as a
    ### link -- never trust it as a redirect target without checking.
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
@db_errors(exec_msg="Database write execution error. Could not delete item safely.")
def itemdeleted(item_to_del):
    ### RE-VALIDATE THE BACK URL HERE TOO -- IT ARRIVED AS A QUERY PARAM
    ### FROM THE CLIENT, SO TREAT IT AS UNTRUSTED EVEN THOUGH itemdel()
    ### ALREADY SANITIZED IT ONCE.
    back_url = safe_relative_url(request.args.get("back_url"))

    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_to_del)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

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

        ### 2. GET ITEM NAME FOR RESULTS PAGE BEFORE DELETION
        item_name_query = """ SELECT item_name FROM items WHERE item_num = %s """
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

        ### 3. EXECUTE DELETION STATEMENT
        del_query = """ DELETE FROM items WHERE item_num = %s """
        cursor = mydb.cursor()
        cursor.execute(del_query, (item_to_del,))
        cursor.close()

    ### PROCESS FILESYSTEM OPERATIONS OUTSIDE DATABASE LOCKS
    photo_dir = ITEM_IMAGE_FS_DIR
    delete_failed = False

    ### ATTEMPT TO DELETE THE PHOTO UNLESS THERE'S NO REAL IMAGE TO DELETE.
    ### "No real image" covers the normal placeholder ("none.jpg") as well
    ### as NULL/empty item_pic values that can show up in older or
    ### imported data -- none of these represent an actual file on disk,
    ### so there's nothing to attempt, let alone fail at.
    has_real_photo = bool(photo_filename) and photo_filename != "none.jpg"

    if has_real_photo:
        ### photo_filename comes out of the database rather than
        ### straight off the request, but treat it as untrusted anyway
        ### and run it through safe_image_path() -- same as every
        ### other photo-delete path in the app (updateitem() above,
        ### cp_photofilesdel() in control_panel.py). Keeps this route
        ### safe even if item_pic ever ends up holding something
        ### unexpected (hand-edited data, a restored backup, a future
        ### code path that doesn't go through the upload flow).
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
            # The file was already gone (e.g. previously cleaned up via
            # the orphan-photos tool, or removed by hand). The end state
            # we wanted -- no orphaned file on disk -- is already true,
            # so this isn't a real failure and shouldn't be reported as
            # one; only genuine errors (permissions, I/O, etc.) below.
            pass
        except Exception:
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
