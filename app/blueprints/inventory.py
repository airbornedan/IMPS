########################################################################
### INVENTORY BLUEPRINT — BROWSING/LISTING BOXES & ITEMS
########################################################################
from flask import Blueprint, request, render_template, make_response
import os
import qrcode

from flask_paginate import Pagination, get_page_parameter

from app.extensions import (
    get_db_connection,
    login_required,
    validate_int,
    ITEM_IMAGE_DIR,
    IMPS_DIR,
    IMPS_IP,
    db_errors,
    run_query,
    get_items_per_page,
    get_offset_for_page,
    InvalidPageError,
)

bp = Blueprint("inventory", __name__)


@bp.route("/inventory")
@login_required
@db_errors(
    conn_msg="Database error when accessing inventory. Could not connect.",
    exec_msg="Database error when retrieving inventory data.",
)
def inventory():
    #####################################
    ############# PAGINATION
    limit = get_items_per_page()
    try:
        offset = get_offset_for_page(limit)
    except InvalidPageError:
        return render_template(
            "errorpage.html",
            err_message="That page number doesn't exist.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### GET NUMBER OF ITEMS FROM DB
        num_query = " SELECT COUNT(*) FROM items  "
        cursor = mydb.cursor()
        cursor.execute(num_query)
        result = cursor.fetchone()
        cursor.close()
        total = result[0]

        ### INVENTORY
        ### SET UP ALL ITEMS QUERY
        inv_query = """ SELECT i.item_num, i.item_name, i.box_num, i.item_pic, i.item_date,
                                c.cat_name AS item_cat, i.item_desc
                         FROM items i
                         JOIN categories c ON i.cat_num = c.cat_num
                         ORDER BY i.item_num DESC
                         LIMIT %s OFFSET %s """

        ### QUERY DB
        cursor = mydb.cursor(dictionary=True)
        cursor.execute(inv_query, (limit, offset))
        result = cursor.fetchall()
        cursor.close()
        item_list = result

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
    ### (inventory.html branches internally on current_view for
    ### mobile vs desktop markup, so a single template covers both)
    current_view = request.cookies.get("view")
    return render_template(
        "inventory.html",
        current_view=current_view,
        item_list=item_list,
        page=page,
        pagination=pagination,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        info_column=info_column,
        photo_column=photo_column,
        date_column=date_column,
        cat_column=cat_column,
        box_column=box_column,
    )


########################################################################
### BOX INTERACTIONS
########################################################################

########################################################################
### LIST OF ALL BOXES
@bp.route("/boxlist")
@login_required
@db_errors(
    conn_msg="Database error when accessing box list. Could not connect.",
    exec_msg="Database error when retrieving box list data.",
)
def boxlist():
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### QUERY FOR ALL BOXES
        allbox_query = """ SELECT b.box_num, l.loc_name, b.box_name, b.box_date, b.box_last_changed
                            FROM boxes b
                            JOIN locations l ON b.loc_num = l.loc_num
                            ORDER BY b.box_num """
        cursor = mydb.cursor()
        cursor.execute(allbox_query)
        box_list = cursor.fetchall()
        cursor.close()

        ### QUERY FOR BOX NUMBERS OF BOXES THAT ARE NOT EMPTY
        not_empty_box_query = """SELECT box_num FROM items WHERE item_num > 0 \
                                 ORDER BY box_num;"""
        cursor = mydb.cursor()
        cursor.execute(not_empty_box_query)
        not_empty_list = cursor.fetchall()
        cursor.close()

    ### CREATE A LIST OF IN-USE BOX NUMBERS
    not_empty_box_num_list = []
    for i in not_empty_list:
        not_empty_box_num_list.append(i[0])

    ### ELIMINATE DUPLICATES
    not_empty_box_num_list = list(set(not_empty_box_num_list))

    ### SHOW THE LIST OF BOXES PAGE
    return render_template(
        "boxes/boxlist.html",
        box_list=box_list,
        not_empty_box_num_list=not_empty_box_num_list,
    )


########################################################################
### LIST BOXES BY LOCATION
@bp.route("/boxlistbyloc/<boxlocation>")
@login_required
@db_errors(
    conn_msg="Database error when accessing box list. Could not connect.",
    exec_msg="Database error when retrieving location data.",
)
def boxlistbyloc(boxlocation):
    box_loc = boxlocation

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### QUERY FOR ALL BOXES AT LOCATION
        boxloc_query = """ SELECT b.box_num, l.loc_name, b.box_name, b.box_date, b.box_last_changed
                            FROM boxes b
                            JOIN locations l ON b.loc_num = l.loc_num
                            WHERE l.loc_name = %s """
        cursor = mydb.cursor()
        cursor.execute(boxloc_query, (box_loc,))
        box_list = cursor.fetchall()
        cursor.close()

        ### QUERY FOR BOX NUMBERS OF BOXES THAT ARE NOT EMPTY
        not_empty_box_query = "SELECT box_num FROM items ORDER BY box_num;"
        cursor = mydb.cursor()
        cursor.execute(not_empty_box_query)
        not_empty_list = cursor.fetchall()
        cursor.close()

    ### CREATE A LIST OF IN-USE BOX NUMBERS
    not_empty_box_num_list = []
    for i in not_empty_list:
        not_empty_box_num_list.append(i[0])

    ### ELIMINATE DUPLICATES
    not_empty_box_num_list = list(set(not_empty_box_num_list))

    ### SHOW THE LIST OF BOXES PAGE
    return render_template(
        "boxes/boxlist.html",
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        not_empty_box_num_list=not_empty_box_num_list,
        box_list=box_list,
        show_location=boxlocation,
    )



########################################################################
### SELECT BOX TO VIEW BY NUMBER
@bp.route("/bybox")
@login_required
@db_errors(
    conn_msg="Database error when accessing box list. Could not connect.",
    exec_msg="Database error when retrieving box structure data.",
)
def bybox():
    # Fetch an active, thread-safe connection from the pool
    available_box_nums_query = "SELECT boxes.box_num FROM boxes;"
    result = run_query(available_box_nums_query)

    ### TURN RESULT INTO A LIST USING COMPREHENSION
    # Extracts the first index of each tuple returned by fetchall()
    available_boxes = [row[0] for row in result]

    ### SHOW BOX SELECTION PAGE
    return render_template(
        "items/bybox.html",
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        available_boxes=available_boxes,
    )


########################################################################
### SELECT CATEGORY TO VIEW
@bp.route("/bycategory")
@login_required
@db_errors(
    conn_msg="Database error when accessing categories. Could not connect.",
    exec_msg="Database error when retrieving categorization data.",
)
def bycategory():
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### QUERY FOR ALL CATEGORIES IN CAT TABLE
        all_cats_query = "SELECT cat_name FROM categories;"
        cursor = mydb.cursor()
        cursor.execute(all_cats_query)
        all_cats_result = cursor.fetchall()
        cursor.close()

        ### QUERY DB FOR ALL CATEGORIES ASSIGNED TO ITEMS
        used_cats_query = """ SELECT DISTINCT c.cat_name FROM items i
                               JOIN categories c ON i.cat_num = c.cat_num """
        cursor = mydb.cursor()
        cursor.execute(used_cats_query)
        used_cats_result = cursor.fetchall()
        cursor.close()

    ### CONVERT TUPLE RESULTS INTO CLEAN LISTS
    all_cats = [row[0] for row in all_cats_result]
    used_cats = [row[0] for row in used_cats_result]

    ### CREATE A LIST OF ONLY THOSE CATS WHICH CONTAIN ITEMS
    available_cats = list(set(all_cats).intersection(used_cats))
    ### SORT THE LIST
    available_cats = sorted(available_cats)

    ### SHOW CATEGORY SELECTION PAGE
    return render_template(
        "items/bycategory.html",
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        available_cats=available_cats,
    )

########################################################################
### SELECT LOCATION TO VIEW
@bp.route("/byloc/")
@login_required
@db_errors(
    conn_msg="Database error when accessing locations. Could not connect.",
    exec_msg="Database error when retrieving location listings.",
)
def byloc():
    # Fetch an active, thread-safe connection from the pool
    used_locs_query = """ SELECT DISTINCT l.loc_name FROM boxes b
                           JOIN locations l ON b.loc_num = l.loc_num """
    result = run_query(used_locs_query)

    ### TURN RESULT INTO A CLEAN LIST AND ELIMINATE DUPES
    used_locs = [row[0] for row in result]
    used_locs = list(set(used_locs))
    available_locs = sorted(used_locs)

    ### SHOW LOCATION SELECTION PAGE
    return render_template(
        "boxes/bylocation.html",
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        available_locs=available_locs,
    )


########################################################################
### SWITCH BOX VIEW
@bp.route("/boxviewswitch/<box_num>")
@login_required
@validate_int("box_num")
@db_errors(
    conn_msg="Database error when accessing box content. Could not connect.",
    exec_msg="Database error when retrieving box contents.",
)
def boxviewswitch(box_num):
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### BOX CONTENT QUERY
        query_statement = """ SELECT i.item_num, i.item_name, i.box_num, i.item_pic, i.item_date,
                                      c.cat_name AS item_cat, i.item_desc
                               FROM items i
                               JOIN categories c ON i.cat_num = c.cat_num
                               WHERE i.box_num = %s """
        cursor = mydb.cursor(dictionary=True)
        cursor.execute(query_statement, (box_num,))
        item_list = cursor.fetchall()
        cursor.close()

        ### BOX NAME QUERY
        box_name_query = """ SELECT box_name FROM boxes WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(box_name_query, (box_num,))
        result = cursor.fetchone()
        cursor.close()

        # Guard clause in case a box row somehow disappeared or doesn't exist
        box_name = result[0] if result else f"Box #{box_num}"

    ### READ THE COLUMN COOKIES
    info_column = request.cookies.get("info_column")
    photo_column = request.cookies.get("photo_column")
    date_column = request.cookies.get("date_column")
    cat_column = request.cookies.get("cat_column")
    box_column = request.cookies.get("box_column")

    ### FLIP THE VIEW COOKIE AND RETURN APPROPRIATE VIEW
    current_view = request.cookies.get("view")

    ### THIS ROUTE FLIPS THE VIEW: render the opposite of current_view,
    ### and set the cookie to match what was just rendered.
    new_view = "desk" if current_view == "mobile" else "mobile"
    response = make_response(
        render_template(
            "items/itemsinbox.html",
            current_view=new_view,
            item_list=item_list,
            box_name=box_name,
            box_num=box_num,
            ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
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
### DISPLAY BOX CONTENTS OF SELECTED BOX
@bp.route("/boxshowcontent/<box_num>", methods=["POST", "GET"])
@login_required
@validate_int("box_num", err_message="Invalid page access. Box number must be an int.")
@db_errors(
    conn_msg="Database error when accessing box contents. Could not connect.",
    exec_msg="Database error when retrieving data for the selected box.",
)
def boxshowcontent(box_num):
    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### BOX NAME QUERY -- also doubles as the existence check: a
        ### box number that was never created (or was since deleted)
        ### has no row here, the one case that should be a hard error.
        ### An empty box (a real box with zero items) is a normal,
        ### expected state, distinct from "box doesn't exist".
        box_name_query = """ SELECT box_name FROM boxes WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(box_name_query, (box_num,))
        box_result = cursor.fetchone()
        cursor.close()

        if not box_result:
            return render_template(
                "errorpage.html",
                err_message="Box "+str(box_num)+" does not exist.",
                err_page_from="/bybox",
            )
        box_name = box_result[0]

        ### BOX CONTENT QUERY
        items_in_box_query = """ SELECT i.item_num, i.item_name, i.box_num, i.item_pic, i.item_date,
                                         c.cat_name AS item_cat, i.item_desc
                                  FROM items i
                                  JOIN categories c ON i.cat_num = c.cat_num
                                  WHERE i.box_num = %s """
        cursor = mydb.cursor(dictionary=True)
        cursor.execute(items_in_box_query, (box_num,))
        item_list = cursor.fetchall()
        cursor.close()

    ### READ THE COLUMN COOKIES
    info_column = request.cookies.get("info_column")
    photo_column = request.cookies.get("photo_column")
    date_column = request.cookies.get("date_column")
    cat_column = request.cookies.get("cat_column")
    box_column = request.cookies.get("box_column")

    ### SHOW THE BOX CONTENT PAGE BASED ON VIEW
    ### (itemsinbox.html branches internally on current_view)
    current_view = request.cookies.get("view")
    response = make_response(
        render_template(
            "items/itemsinbox.html",
            current_view=current_view,
            item_list=item_list,
            box_name=box_name,
            box_num=box_num,
            ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            info_column=info_column,
            photo_column=photo_column,
            date_column=date_column,
            cat_column=cat_column,
            box_column=box_column,
        )
    )
    return response


########################################################################
### CREATE AND SHOW BOX LABEL / QR CODE
@bp.route("/boxlabel/<box_num>")
@login_required
@validate_int("box_num", err_message="Invalid page access. Box number must be an integer.")
@db_errors(
    conn_msg="Database error when accessing box QR. Could not connect.",
    exec_msg="Database error when retrieving label naming metrics.",
)
def boxlabel(box_num):
    # Fetch an active, thread-safe connection from the pool
    box_name_query = """ SELECT box_name FROM boxes WHERE box_num = %s """
    result = run_query(box_name_query, (box_num,), fetch="one")

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Box number not in database.",
            err_page_from="/",
        )
    box_name = result[0]

    ### ASSIGN QR VARIABLES
    qr_url = f"http://{IMPS_IP}/boxshowcontent/{box_num}"

    ### CALL QR LIBRARY TO MAKE THE QR IMAGE
    img = qrcode.make(qr_url)

    ### SAVE THE IMAGE
    ### qrcodes_fs_dir is anchored to IMPS_DIR (not the process's cwd),
    ### same reasoning as BACKUP_DIR/ITEM_IMAGE_FS_DIR in extensions.py.
    ### os.makedirs(..., exist_ok=True) ensures static/images/qrcodes/
    ### exists (gitignored, no tracked content) before the first label
    ### print tries to save into it.
    qrcodes_fs_dir = os.path.join(IMPS_DIR, "static", "images", "qrcodes")
    os.makedirs(qrcodes_fs_dir, exist_ok=True)
    save_location = os.path.join(qrcodes_fs_dir, f"qr_code_for_box_{box_num}.png")
    img.save(save_location)

    ### SET THE QR FILE LOCATION (URL-relative, for the <img> tag in
    ### boxprintlabel.html -- deliberately NOT the same as
    ### save_location above; same reasoning as ITEM_IMAGE_DIR vs
    ### ITEM_IMAGE_FS_DIR in extensions.py)
    qr_image_url = f"/static/images/qrcodes/qr_code_for_box_{box_num}.png"

    ### SHOW THE LABEL
    return render_template(
        "boxes/boxprintlabel.html",
        box_num=box_num,
        qr_image_url=qr_image_url,
        box_name=box_name,
    )
