########################################################################
### BOXES BLUEPRINT — CREATE/EDIT/DELETE BOXES, MOVE/ORPHAN ITEMS
########################################################################
from flask import Blueprint, request, render_template, redirect, url_for, make_response, session
from array import array
from datetime import date
from mysql.connector.errors import IntegrityError

from app.extensions import get_db_connection, DBConnectionError, login_required, limiter, logger, db_errors, run_query

bp = Blueprint("boxes", __name__)


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
    ### GET FORM DATA
    old_box_num = request.form["box_to_del"]

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
    ### GET FORM DATA
    box_to_del = request.form["box_to_del"]

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
    ### GET FORM DATA
    box_to_del = request.form["box_to_del"]

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
        ### ORPHAN ITEMS QUERY
        orphan_query = """ UPDATE items SET box_num = NULL WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(orphan_query, (box_to_del,))
        cursor.close()

        ### BOX DELETE QUERY
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
    ### GET FORM DATA
    box_to_del = request.form["box_to_del"]
    new_box_num = request.form["new_box_num"]

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
        ### MOVE ITEMS TO NEW BOX QUERY
        move_query = """ UPDATE items SET box_num = %s WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(move_query, (new_box_num, box_to_del))
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
    box_name = request.form.get("box_name")

    ### IF NO LOCATION WAS SELECTED, SET TO UNSPECIFIED
    if box_loc is None or box_loc == "":
        box_loc = "Unspecified"

    ### IF NEXT AVAILABLE IS SET, USE THAT BOX
    if box_type == "next_available":
        box_num = next_available_box_num

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### ENSURE THE LOCATION EXISTS. Relies on the loc_name UNIQUE
        ### constraint: attempts the insert, and a duplicate-key error
        ### simply means the location already exists.
        add_loc_query = """ INSERT INTO locations (loc_name) VALUES (%s) """
        cursor = mydb.cursor()
        try:
            cursor.execute(add_loc_query, (box_loc,))
        except IntegrityError:
            pass  # location already exists -- nothing to do
        cursor.close()

        current_date = str(date.today())

        ### INSERT NEW BOX DATA INTO DB
        query_vars = (box_num, box_loc, box_name, current_date, current_date)
        query_string = """ INSERT INTO boxes (box_num, box_loc, box_name, box_date,\
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

        ### NOTE: an empty not_empty_result here is a normal, valid
        ### state -- it just means every existing box is currently
        ### empty (e.g. boxes were created but nothing's been added
        ### to them yet), not a database failure.

    ### CONVERT TUPLE RESULTS INTO CLEAN LISTS VIA COMPREHENSIONS
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

    ### GET FORM DATA
    box_to_del = request.form["box_to_del"]

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_to_del)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ### GET ADDITIONAL FORM DATA
    item_handling = request.form["item_handling"]

    ### CHECK IF BOX HAS CONTENTS
    box_state_query = """ SELECT * FROM items WHERE box_num = %s """

    with get_db_connection() as mydb:
        box_state_query = """SELECT * FROM items WHERE box_num = %s"""

        cursor = mydb.cursor()
        cursor.execute(box_state_query, (box_to_del,))
        result = cursor.fetchall()
        cursor.close()

        box_state = "empty" if len(result) == 0 else "not_empty"

    ### DETERMINE IF BOX IS EMPTY OR NOT
    if cursor.rowcount == 0:
        box_state = "empty"
    else:
        box_state = "not_empty"
    cursor.close()

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
        available_box_nums_query = "SELECT boxes.box_num FROM boxes;"

        cursor = mydb.cursor()
        cursor.execute(available_box_nums_query)
        result = cursor.fetchall()
        cursor.close()

        if not result:
            return render_template(
                "errorpage.html",
                err_message="Database error.",
                err_page_from="/",
            )

    ### CHECK THAT QUERY SUCCEEDED
    if not result:
        return render_template(
            "errorpage.html",
            err_message="Database error.",
            err_page_from="/",
        )

    num_items = len(result)
    cursor.close()

    ### TURN RESULT INTO A LIST
    available_boxes = []
    for i in range(num_items):
        container = list(result[i])
        available_boxes.insert(1, container.pop())

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
        box_details_query = """ SELECT * FROM boxes WHERE box_num = %s """
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
    box_desc = box_details[0][2]

    ### SHOW BOX DETAILS
    return render_template(
        "boxes/boxdetails.html",
        box_num=box_num,
        box_desc=box_desc,
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
    box_name = request.form.get("box_name")
    box_loc = request.form.get("box_loc")
    box_num = request.form.get("box_num")

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ### 1. PROCESS BOX RECORD MUTATIONS
        if box_loc == "":
            box_update_query = """ UPDATE boxes SET box_name = %s WHERE box_num = %s """
            cursor = mydb.cursor()
            cursor.execute(box_update_query, (box_name, box_num))
            cursor.close()

            ### READ THE PRE-EXISTING LOCATION BACK TO SEND BACK TO THE TEMPLATE
            box_loc_query = """ SELECT box_loc FROM boxes WHERE box_num = %s """
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
            box_update_query = """ UPDATE boxes SET box_name = %s , box_loc = %s WHERE box_num = %s """
            cursor = mydb.cursor()
            cursor.execute(box_update_query, (box_name, box_loc, box_num))
            cursor.close()

        ### 2. ENSURE THE LOCATION EXISTS -- relies on the loc_name
        ### UNIQUE constraint plus a caught IntegrityError, rather than
        ### a SELECT-then-check-then-INSERT, which would be a race
        ### condition (two concurrent requests could both pass the
        ### check before either INSERT lands, producing duplicate rows).
        if box_loc != "":
            add_loc_query = """ INSERT INTO locations (loc_name) VALUES (%s) """
            cursor = mydb.cursor()
            try:
                cursor.execute(add_loc_query, (box_loc,))
            except IntegrityError:
                pass  # location already exists -- nothing to do
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
        ### (checked here, ahead of time, so a collision shows a clear
        ### message -- the UNIQUE constraint on boxes.box_num would
        ### also catch this at the database level, which is what
        ### integrity_msg above is for as a defense-in-depth backstop,
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

        ### CASCADE TO EVERY ITEM CURRENTLY IN THIS BOX
        ### items.box_num has no foreign key constraint tying it to
        ### boxes.box_num (see schema.sql) -- nothing enforces this at
        ### the database level, so skipping this step would silently
        ### orphan every item in the box (same "orphaned" state the
        ### control panel's orphan-items tool already exists to find
        ### and clean up, which is exactly the mess this cascade avoids
        ### creating in the first place).
        items_update_query = """ UPDATE items SET box_num = %s WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(items_update_query, (new_box_num, old_box_num))
        cursor.close()

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
        ### QUERY TO DELETE BOX
        del_box_query = """ DELETE FROM boxes WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(del_box_query, (box_to_del,))
        cursor.close()

        ### QUERY TO DELETE ITEMS IN THAT BOX
        del_items_query = """ DELETE FROM items WHERE box_num = %s """
        cursor = mydb.cursor()
        cursor.execute(del_items_query, (box_to_del,))
        cursor.close()

    ### SHOW BOX DELETE SUCCESS PAGE
    return render_template("boxes/boxdelsuccess.html", box_to_del=box_to_del)
