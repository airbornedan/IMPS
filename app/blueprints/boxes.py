########################################################################
### BOXES BLUEPRINT — CREATE/EDIT/DELETE BOXES, MOVE/ORPHAN ITEMS
########################################################################
from flask import Blueprint, request, render_template
from datetime import date

from app.extensions import (
    get_db_connection,
    login_required,
    limiter,
    db_errors,
    run_query,
    MAX_BOX_NUM,
    MAX_LOCATION_NAME_LENGTH,
    MAX_BOX_NAME_LENGTH,
    get_or_create_loc_num,
    touch_box_last_changed,
)

bp = Blueprint("boxes", __name__)

# boxes.loc_num is a numeric foreign key rather than a copy of the
# location name, so every box read needs locations joined in. Every
# consumer (this file's unpacking below, templates like
# boxdetails.html) expects a 5-column tuple in
# (box_num, box_loc, box_name, box_date, box_last_changed) order.
# Aliasing l.loc_name into the 2nd position keeps that order intact.
# Kept as one shared constant so read sites can't drift out of sync.
BOXES_WITH_LOC_NAME = """
    SELECT b.box_num, l.loc_name, b.box_name, b.box_date, b.box_last_changed
    FROM boxes b
    JOIN locations l ON b.loc_num = l.loc_num
"""


@bp.route("/boxadd")
@login_required
@db_errors(
    conn_msg="Database error when accessing box structural parameters. Could not connect.",
    exec_msg="Database error when parsing layout values.",
)
def boxadd():
    with get_db_connection() as mydb:
        ### QUERY ALL LOCATIONS
        loc_query = "SELECT * FROM locations;"
        cursor = mydb.cursor()
        cursor.execute(loc_query)
        locations_result = cursor.fetchall()
        cursor.close()

        if not locations_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access box locations.",
                err_page_from="/",
            )

        ### QUERY BOX NUMS CURRENTLY IN USE
        available_box_nums_query = "SELECT box_num FROM boxes ORDER BY box_num;"
        cursor = mydb.cursor()
        cursor.execute(available_box_nums_query)
        box_nums_result = cursor.fetchall()
        cursor.close()

    ### CONVERT TUPLE RESULTS TO CLEAN STRUCTURES
    locations = locations_result
    box_nums = [row[0] for row in box_nums_result]

    ### FIND THE FIRST AVAILABLE BOX NUMBER (GAP FINDING LOGIC)
    first_available_box = None
    
    # Check if box #1 is missing altogether
    if not box_nums or box_nums[0] > 1:
        first_available_box = 1
    else:
        # Find structural numerical gaps between elements
        for i in range(len(box_nums) - 1):
            if box_nums[i + 1] - box_nums[i] > 1:
                first_available_box = box_nums[i] + 1
                break

    ### IF NO GAP, ADD NEW BOX AT THE SEQUENTIAL END
    if not first_available_box:
        first_available_box = len(box_nums) + 1 if box_nums else 1

    ### SHOW THE ADD BOX PAGE
    return render_template(
        "boxes/boxadd.html",
        locations=locations,
        box_nums=box_nums,
        first_available_box=first_available_box,
    )


########################################################################
@bp.route("/boxmoveitemsconf", methods=["POST"])
@login_required
@db_errors(
    conn_msg="Database error when accessing box numbers. Could not connect.",
    exec_msg="Database error when retrieving global box configuration structures.",
)
def boxmoveitems():
    ### GET FORM DATA. Use .get() with a "" default (rather than
    ### request.form["box_to_del"]) so a malformed/incomplete POST (stale
    ### cached page, bookmarked/replayed request) falls through to the
    ### int() check below, showing IMPS's own error page instead of an
    ### unhandled KeyError (a generic Flask 400).
    old_box_num = request.form.get("box_to_del", "")

    ### VERIFY FORM ENTRY IS AN INT
    try:
        check_int = int(old_box_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Invalid entry. Box number must be an int.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    available_box_nums_query = "SELECT box_num FROM boxes ORDER BY box_num;"
    result = run_query(available_box_nums_query)

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Database error. Could not access box numbers.",
            err_page_from="/",
        )
    ### TURN RESULT INTO A LIST USING COMPREHENSION
    available_boxes = [row[0] for row in result]

    ### SHOW THE PAGE
    return render_template(
        "boxes/boxmoveitemsconf.html",
        available_boxes=available_boxes,
        old_box_num=old_box_num,
    )


########################################################################
@bp.route("/boxorphanitemsconf", methods=["POST"])
@login_required
@db_errors(
    conn_msg="Database error when accessing box info. Could not connect.",
    exec_msg="Database error when parsing item dependencies.",
)
def boxorphanitems():
    ### GET FORM DATA. Use .get() with a "" default -- see
    ### boxmoveitems() above for why.
    box_to_del = request.form.get("box_to_del", "")

    ### VERIFY FORM ENTRY IS AN INT
    try:
        check_int = int(box_to_del)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    box_state_query = """ SELECT * FROM items WHERE box_num = %s """
    result = run_query(box_state_query, (box_to_del,))

    # Use simple array length verification instead of volatile rowcounts
    if len(result) == 0:
        box_state = "empty"
    else:
        box_state = "not_empty"

    ### SHOW ORPHAN ITEMS PAGE
    return render_template(
        "boxes/boxorphanitemsconf.html", 
        box_to_del=box_to_del, 
        box_state=box_state
    )

########################################################################
@bp.route("/boxorphanitemssuccess", methods=["POST"])
@login_required
@db_errors(
    conn_msg="Database error when updating box. Could not connect.",
    exec_msg="Database error. Could not process item updates or box removal.",
)
def boxorphanitemssuccess():
    ### GET FORM DATA. Use .get() with a "" default -- see
    ### boxmoveitems() above for why.
    box_to_del = request.form.get("box_to_del", "")

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_to_del)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### BOX DELETE QUERY -- items.box_num is a real foreign key
        ### (ON DELETE SET NULL, see deploy/schema.sql), so deleting
        ### the box automatically sets box_num = NULL on every item
        ### that was in it. No separate UPDATE needed to orphan them.
        box_del_query = """ DELETE FROM boxes WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(box_del_query, (box_to_del,))
        cursor.close()

    return render_template("boxes/boxorphanitemssuccess.html")


########################################################################
@bp.route("/boxmoveitemssuccess", methods=["POST"])
@login_required
@db_errors(
    conn_msg="Database error when moving items. Could not connect.",
    exec_msg="Database error. Could not migrate items or delete box mapping.",
)
def boxmoveitemssuccess():
    ### GET FORM DATA. Use .get() with "" defaults -- see
    ### boxmoveitems() above for why.
    box_to_del = request.form.get("box_to_del", "")
    new_box_num = request.form.get("new_box_num", "")

    ### VERIFY VARIABLES ARE INTS
    try:
        check_int = int(box_to_del) + int(new_box_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Invalid entry. Box number must be an int.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### MOVE ITEMS TO NEW BOX QUERY -- this has to run BEFORE the
        ### box is deleted below. items.box_num is a real foreign
        ### key with ON DELETE SET NULL (see deploy/schema.sql/
        ### boxorphanitemssuccess() above) -- if the box were deleted
        ### first, every item still pointing at it would already have
        ### been set to NULL by the FK before this UPDATE's WHERE
        ### box_num = %s (old box) could ever match them.
        move_query = """ UPDATE items SET box_num = %s WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(move_query, (new_box_num, box_to_del))
        cursor.close()

        ### TOUCH THE DESTINATION BOX -- every item from the deleted
        ### box just arrived in it. (box_to_del isn't touched: it's
        ### deleted immediately below, moot.) See
        ### touch_box_last_changed() in extensions.py.
        cursor = mydb.cursor()
        touch_box_last_changed(cursor, new_box_num)
        cursor.close()

        ### DELETE BOX QUERY
        box_del_query = """ DELETE FROM boxes WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(box_del_query, (box_to_del,))
        cursor.close()

    return render_template(
        "boxes/boxmoveitemssuccess.html",
        new_box_num=new_box_num,
        deleted_box=box_to_del,
    )



########################################################################
### ADD BOX TO DB AND SHOW SUCCESS PAGE
@bp.route("/boxadded", methods=["POST"])
@login_required
@limiter.limit("30 per minute; 300 per hour")
@db_errors(
    exec_msg="Database error. Could not append structural definitions or add box data.",
)
def boxadded():
    ### GET FORM DATA AND CHECK BOX NUMBER TYPE SELECTION
    box_type = request.form.get("box_type")
    
    if box_type == "next_available":
        box_num = request.form.get("next_num")
    else:
        box_num = request.form.get("box_num")

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Invalid entry. Box number must be an int.",
            err_page_from="/",
        )

    ### GET ADDITIONAL FORM DATA
    next_available_box_num = request.form.get("next_available_box_num")
    box_loc = request.form.get("box_loc")
    box_name = request.form.get("box_name") or ""

    ### VALIDATE BOX NAME LENGTH -- UI enforces this via maxlength + JS
    ### (see boxadd.html), client-side only -- a direct POST bypasses
    ### it, so it's checked here too.
    if len(box_name) > MAX_BOX_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=f"Box names are limited to {MAX_BOX_NAME_LENGTH} characters.",
            err_page_from="/boxadd",
        )

    ### IF NO LOCATION WAS SELECTED, SET TO UNSPECIFIED
    if box_loc is None or box_loc == "":
        box_loc = "Unspecified"

    ### VALIDATE LOCATION NAME LENGTH -- box_loc doubles as a
    ### free-text "create a new location" field (see get_or_create_loc_num()
    ### below), so it's not limited to picking an existing name. UI
    ### enforces this via maxlength + JS (see boxadd.html), client-side
    ### only -- a direct POST bypasses it, so it's checked here too.
    if len(box_loc) > MAX_LOCATION_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=f"Location names are limited to {MAX_LOCATION_NAME_LENGTH} characters.",
            err_page_from="/boxadd",
        )

    ### IF NEXT AVAILABLE IS SET, USE THAT BOX
    if box_type == "next_available":
        box_num = next_available_box_num

    ### RE-VALIDATE THE FINAL box_num -- next_available_box_num comes
    ### from a hidden/readonly form field, only "read-only" in the UI,
    ### not enforced server-side; a direct POST could substitute
    ### anything. Also enforces the MAX_BOX_NUM cap. UI already
    ### enforces this cap via maxlength="4" + JS (see boxadd.html),
    ### client-side only.
    try:
        final_box_num = int(box_num)
    except (ValueError, TypeError):
        return render_template(
            "errorpage.html",
            err_message="Invalid entry. Box number must be an int.",
            err_page_from="/",
        )

    if final_box_num < 0:
        return render_template(
            "errorpage.html",
            err_message="Box numbers must be positive.",
            err_page_from="/boxadd",
        )

    if final_box_num > MAX_BOX_NUM:
        return render_template(
            "errorpage.html",
            err_message="The number entered was greater than the greatest allowable box number.",
            err_page_from="/boxadd",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### ENSURE THE LOCATION EXISTS AND RESOLVE ITS loc_num --
        ### relies on the loc_name UNIQUE constraint plus a caught
        ### IntegrityError rather than a SELECT-then-check-then-INSERT,
        ### which would be a race condition. See get_or_create_loc_num()
        ### in extensions.py.
        cursor = mydb.cursor()
        loc_num = get_or_create_loc_num(cursor, box_loc)
        cursor.close()

        current_date = str(date.today())

        ### INSERT NEW BOX DATA INTO DB
        query_vars = (box_num, loc_num, box_name, current_date, current_date)
        query_string = """ INSERT INTO boxes (box_num, loc_num, box_name, box_date,\
            box_last_changed) VALUES (%s,%s,%s,%s,%s) """

        cursor = mydb.cursor()
        cursor.execute(query_string, query_vars)
        cursor.close()

    ### SHOW SUCCESS PAGE
    return render_template(
        "boxes/boxadded.html", 
        box_num=box_num, 
        box_loc=box_loc, 
        box_name=box_name
    )


########################################################################
### DELETE BOX
@bp.route("/boxdel", methods=["POST", "GET"])
@login_required
@db_errors(exec_msg="Database error when retrieving box deletion parameters.")
def boxdel():
    box_to_del = ""

    ### GET FORM DATA IF FROM BOX DEL PAGE
    if request.method == "POST":
        box_to_del = request.form.get("box_to_del", "")

        ### VERIFY VARIABLE IS AN INT
        try:
            check_int = int(box_to_del)
        except ValueError:
            return render_template(
                "errorpage.html",
                err_message="Entry is not a number.",
                err_page_from="/",
            )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### QUERY BOX NUMBERS CURRENTLY IN USE
        available_box_nums_query = "SELECT box_num FROM boxes ORDER BY box_num;"
        cursor = mydb.cursor()
        cursor.execute(available_box_nums_query)
        available_result = cursor.fetchall()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not available_result:
            return render_template(
                "errorpage.html",
                err_message="Database error. Could not access available boxes",
                err_page_from="/",
            )

        ### QUERY BOX NUMBERS OF BOXES THAT ARE NOT EMPTY
        not_empty_box_query = "SELECT box_num FROM items WHERE item_num > 0 ORDER BY box_num;"
        cursor = mydb.cursor()
        cursor.execute(not_empty_box_query)
        not_empty_result = cursor.fetchall()
        cursor.close()

        ### NOTE: an empty not_empty_result is normal and valid -- it
        ### just means every existing box is currently empty (created
        ### but nothing added yet), not a database failure.

    ### EXTRACT BOX NUMBERS
    box_nums = [row[0] for row in available_result]
    not_empty_box_num_list = [row[0] for row in not_empty_result]

    ### ELIMINATE DUPLICATES
    not_empty_box_num_list = list(set(not_empty_box_num_list))

    ### SHOW THE DEL BOX PAGE
    return render_template(
        "boxes/boxdel.html",
        box_nums=box_nums,
        not_empty_box_num_list=not_empty_box_num_list,
        box_to_del=box_to_del,
    )



########################################################################
### DELETE BOX CONFIRM PAGE
@bp.route("/delboxconf", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error. Could not access box list.")
def delboxconf():

    ### GET FORM DATA. Use .get() with a "" default -- see
    ### boxmoveitems() above for why.
    box_to_del = request.form.get("box_to_del", "")

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_to_del)
    except (ValueError, TypeError):
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ### CHECK IF BOX HAS CONTENTS
    box_state_query = """ SELECT * FROM items WHERE box_num = %s """

    with get_db_connection() as mydb:
        cursor = mydb.cursor()
        cursor.execute(box_state_query, (box_to_del,))
        result = cursor.fetchall()
        cursor.close()

        box_state = "empty" if len(result) == 0 else "not_empty"

    ### SHOW THE BOX DELETE CONFIRMATION PAGE
    return render_template(
        "boxes/boxdelconfirm.html", box_state=box_state, box_to_del=box_to_del
    )


########################################################################
### EDIT BOX FORM
@bp.route("/boxedit")
@login_required
@db_errors(exec_msg="Database error. Could not access box list.")
def boxedit():

    ### SETUP AVAILABLE BOX NUMERS QUERY
    available_box_nums_query = "SELECT boxes.box_num FROM boxes;"

    with get_db_connection() as mydb:
        cursor = mydb.cursor()
        cursor.execute(available_box_nums_query)
        result = cursor.fetchall()
        cursor.close()

        ### CHECK THAT QUERY SUCCEEDED
        if not result:
            return render_template(
                "errorpage.html",
                err_message="Database error.",
                err_page_from="/",
            )

    ### TURN RESULT INTO A LIST
    available_boxes = [row[0] for row in result]

    ### RETURN BOX SELECTION PAGE
    return render_template("boxes/boxedit.html", available_boxes=available_boxes)


########################################################################
### SHOW BOX DETAILS
@bp.route("/boxdetails", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error. Could not access box configuration records.")
def boxdetails():
    ### SET UP BOX DETAILS QUERY
    box_num = request.form.get("box-num")

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### QUERY BOX
        box_details_query = BOXES_WITH_LOC_NAME + " WHERE b.box_num = %s "
        cursor = mydb.cursor()
        cursor.execute(box_details_query, (box_num,))
        box_details = cursor.fetchall()
        cursor.close()

        # Guard clause in case a user selects a box number that was recently deleted
        if not box_details:
            return render_template(
                "errorpage.html",
                err_message="The selected box no longer exists in the database.",
                err_page_from="/boxedit",
            )

        ### QUERY ALL LOCATIONS
        loc_query = "SELECT * FROM locations"
        cursor = mydb.cursor()
        cursor.execute(loc_query)
        locations = cursor.fetchall()
        cursor.close()

    ### ASSIGN VALUES TO FORM VARIABLES FROM FIRST FETCHED ROW
    box_num = box_details[0][0]
    box_loc = box_details[0][1]
    box_name = box_details[0][2]

    ### SHOW BOX DETAILS
    return render_template(
        "boxes/boxdetails.html",
        box_num=box_num,
        box_name=box_name,
        box_loc=box_loc,
        locations=locations,
    )

########################################################################
### WRITE BOX CHANGES TO DB AND SHOW SUCCESS PAGE
@bp.route("/boxedited", methods=["GET", "POST"])
@login_required
@db_errors(exec_msg="Database error. Could not successfully complete updating box metrics.")
def boxeditsuccess():
    ### GET FORM DATA
    box_name = request.form.get("box_name") or ""
    box_loc = request.form.get("box_loc")
    box_num = request.form.get("box_num")

    ### VALIDATE BOX NAME LENGTH -- UI enforces this via maxlength + JS
    ### (see boxdetails.html), client-side only -- a direct POST
    ### bypasses it, so it's checked here too.
    if len(box_name) > MAX_BOX_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=f"Box names are limited to {MAX_BOX_NAME_LENGTH} characters.",
            err_page_from="/boxedit",
        )

    ### VALIDATE LOCATION NAME LENGTH -- box_loc == "" means "keep the
    ### existing location" (handled below), so only a genuinely
    ### submitted name needs checking. Doubles as a free-text "create a
    ### new location" field (see get_or_create_loc_num() below). UI
    ### enforces this via maxlength + JS (see boxdetails.html),
    ### client-side only -- a direct POST bypasses it, so it's checked
    ### here too.
    if box_loc and len(box_loc) > MAX_LOCATION_NAME_LENGTH:
        return render_template(
            "errorpage.html",
            err_message=f"Location names are limited to {MAX_LOCATION_NAME_LENGTH} characters.",
            err_page_from="/boxedit",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. PROCESS BOX RECORD MUTATIONS. box_last_changed is set
        ### here directly (not via touch_box_last_changed()) since
        ### this route already writes this exact row -- see
        ### touch_box_last_changed() in extensions.py for what else
        ### counts as a box "touch".
        if box_loc == "":
            box_update_query = """ UPDATE boxes SET box_name = %s, box_last_changed = %s WHERE box_num = %s """
            cursor = mydb.cursor()
            cursor.execute(box_update_query, (box_name, str(date.today()), box_num))
            cursor.close()

            ### READ THE PRE-EXISTING LOCATION NAME BACK (via the
            ### locations join, since boxes.loc_num is a numeric FK
            ### rather than the name itself) TO SEND TO THE TEMPLATE
            box_loc_query = """ SELECT l.loc_name FROM boxes b
                                 JOIN locations l ON b.loc_num = l.loc_num
                                 WHERE b.box_num = %s """
            cursor = mydb.cursor()
            cursor.execute(box_loc_query, (box_num,))
            result = cursor.fetchone()
            cursor.close()

            if not result:
                return render_template(
                    "errorpage.html",
                    err_message="Database error. Could not retrieve updated box state data.",
                    err_page_from="/",
                )
            box_loc = result[0]
        else:
            ### RESOLVE THE SUBMITTED LOCATION NAME TO ITS loc_num,
            ### CREATING THE LOCATION IF IT'S A BRAND NEW NAME -- relies
            ### on the loc_name UNIQUE constraint plus a caught
            ### IntegrityError rather than a SELECT-then-check-then-
            ### INSERT, which would be a race condition. See
            ### get_or_create_loc_num() in extensions.py.
            cursor = mydb.cursor()
            loc_num = get_or_create_loc_num(cursor, box_loc)
            cursor.close()

            box_update_query = """ UPDATE boxes SET box_name = %s , loc_num = %s, box_last_changed = %s WHERE box_num = %s """
            cursor = mydb.cursor()
            cursor.execute(box_update_query, (box_name, loc_num, str(date.today()), box_num))
            cursor.close()

    ### SHOW SUCCESS PAGE
    return render_template(
        "boxes/boxedited.html", box_name=box_name, box_loc=box_loc, box_num=box_num
    )


########################################################################
### SHOW THE "CHANGE BOX NUMBER" FORM

@bp.route("/boxrenumber/<box_num>")
@login_required
@db_errors(
    conn_msg="Database error when accessing box info. Could not connect.",
    exec_msg="Database error when retrieving box renumbering data.",
)
def boxrenumber(box_num):
    ### VERIFY ROUTE PARAMETER IS AN INT
    try:
        check_int = int(box_num)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Invalid page access. Box number must be an integer.",
            err_page_from="/boxlist",
        )

    with get_db_connection() as mydb:
        ### CONFIRM THE BOX EXISTS
        box_query = """ SELECT box_num FROM boxes WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(box_query, (box_num,))
        box_result = cursor.fetchone()
        cursor.close()

        if not box_result:
            return render_template(
                "errorpage.html",
                err_message="The selected box no longer exists in the database.",
                err_page_from="/boxlist",
            )

        ### COUNT ITEMS CURRENTLY IN THIS BOX (shown in the warning
        ### text and the confirm step, so the person knows exactly
        ### what a renumber will affect, not just an abstract warning)
        item_count_query = """ SELECT COUNT(*) FROM items WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(item_count_query, (box_num,))
        item_count = cursor.fetchone()[0]
        cursor.close()

        ### ALL BOX NUMBERS CURRENTLY IN USE (for the same client-side
        ### "already in use" live validation pattern as boxadd.html)
        box_nums_query = "SELECT box_num FROM boxes ORDER BY box_num;"
        cursor = mydb.cursor()
        cursor.execute(box_nums_query)
        box_nums_result = cursor.fetchall()
        cursor.close()

    box_nums = [row[0] for row in box_nums_result]

    return render_template(
        "boxes/boxrenumber.html",
        box_num=box_num,
        item_count=item_count,
        box_nums=box_nums,
    )


########################################################################
### CHANGE THE BOX NUMBER AND CASCADE TO ITEMS, THEN SHOW SUCCESS PAGE
@bp.route("/boxrenumbersuccess", methods=["POST"])
@login_required
@db_errors(
    conn_msg="Database error when accessing box info. Could not connect.",
    exec_msg="Database error. Could not successfully change the box number.",
    integrity_msg="That box number is already in use. Choose a different number.",
)
def boxrenumbersuccess():
    old_box_num = request.form.get("old_box_num")
    new_box_num = request.form.get("new_box_num")

    ### VERIFY BOTH ARE INTS
    try:
        check_old = int(old_box_num)
        check_new = int(new_box_num)
    except (ValueError, TypeError):
        return render_template(
            "errorpage.html",
            err_message="Box numbers must be integers.",
            err_page_from="/boxlist",
        )

    if check_new == check_old:
        return render_template(
            "errorpage.html",
            err_message="That's already this box's number -- choose a different one.",
            err_page_from=f"/boxrenumber/{old_box_num}",
        )

    if check_new < 0:
        return render_template(
            "errorpage.html",
            err_message="Box numbers must be positive.",
            err_page_from=f"/boxrenumber/{old_box_num}",
        )

    ### ENFORCE THE MAX_BOX_NUM CAP. The UI already enforces this via
    ### maxlength="4" + JS (see boxrenumber.html), but that's
    ### client-side only -- a direct POST bypasses it entirely.
    if check_new > MAX_BOX_NUM:
        return render_template(
            "errorpage.html",
            err_message="The number entered was greater than the greatest allowable box number.",
            err_page_from=f"/boxrenumber/{old_box_num}",
        )

    with get_db_connection() as mydb:
        ### CONFIRM THE OLD BOX STILL EXISTS
        box_query = """ SELECT box_num FROM boxes WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(box_query, (old_box_num,))
        box_result = cursor.fetchone()
        cursor.close()

        if not box_result:
            return render_template(
                "errorpage.html",
                err_message="The selected box no longer exists in the database.",
                err_page_from="/boxlist",
            )

        ### CONFIRM THE NEW NUMBER ISN'T ALREADY IN USE
        ### (checked here for a clear message; the UNIQUE constraint on
        ### boxes.box_num also catches this at the DB level --
        ### integrity_msg above is a defense-in-depth backstop for that,
        ### e.g. a race condition, not the primary path)
        existing_query = """ SELECT box_num FROM boxes WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(existing_query, (new_box_num,))
        existing_result = cursor.fetchone()
        cursor.close()

        if existing_result:
            return render_template(
                "errorpage.html",
                err_message=f"Box {new_box_num} already exists. Choose a different number.",
                err_page_from=f"/boxrenumber/{old_box_num}",
            )

        ### COUNT ITEMS BEING MOVED, FOR THE SUCCESS PAGE
        item_count_query = """ SELECT COUNT(*) FROM items WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(item_count_query, (old_box_num,))
        item_count = cursor.fetchone()[0]
        cursor.close()

        ### UPDATE THE BOX ITSELF
        box_update_query = """ UPDATE boxes SET box_num = %s WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(box_update_query, (new_box_num, old_box_num))
        cursor.close()

        ### items.box_num is a real foreign key with ON UPDATE CASCADE
        ### (see deploy/schema.sql) -- the database itself propagates
        ### the box_num change above to every item that was in this
        ### box, automatically. No separate UPDATE needed here.

    return render_template(
        "boxes/boxrenumbersuccess.html",
        old_box_num=old_box_num,
        new_box_num=new_box_num,
        item_count=item_count,
    )


########################################################################
### DELETE BOX FROM DB AND SHOW SUCCESS PAGE
@bp.route("/boxdeletesuccess/<box_to_del>", methods=["POST"])
@login_required
@db_errors(exec_msg="Database error. Could not successfully delete box or associated inventory items.")
def boxdeletesuccess(box_to_del):
    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(box_to_del)
    except ValueError:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### QUERY TO DELETE ITEMS IN THAT BOX -- MUST run before the box
        ### itself is deleted below. items.box_num has ON DELETE SET
        ### NULL (see deploy/schema.sql): if the box were deleted
        ### first, remaining items would already have box_num set to
        ### NULL by the FK before this WHERE box_num = %s could match
        ### them, so they'd silently survive as orphans instead of
        ### being deleted. This path -- reached from boxdelconfirm.html
        ### -- is IMPS's "delete this box and everything in it" action,
        ### distinct from the orphan/move flow in
        ### boxorphanitemssuccess()/boxmoveitemssuccess() above.
        del_items_query = """ DELETE FROM items WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(del_items_query, (box_to_del,))
        cursor.close()

        ### QUERY TO DELETE BOX
        del_box_query = """ DELETE FROM boxes WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(del_box_query, (box_to_del,))
        cursor.close()

    ### SHOW BOX DELETE SUCCESS PAGE
    return render_template("boxes/boxdelsuccess.html", box_to_del=box_to_del)
