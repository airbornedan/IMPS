from flask import (
    Flask,
    request,
    render_template,
    redirect,
    url_for,
    make_response,
    request,
)
import configparser
import toml
import mysql.connector as sql_db
from mysql.connector import errorcode
import gzip
import datetime
import time
from datetime import date
import pathlib
from array import array
import re
import requests
import os

# import pymysql
import qrcode
from werkzeug.utils import secure_filename

app = Flask(__name__)

global saved_search

########################################################################
### IMPORT CONFIGURATION
########################################################################

with open("imps_config.toml", mode="r") as f:
    imps_config = toml.load(f)

global dbhost
dbhost = imps_config['database']['host']
global dbname
dbname = imps_config['database']['name']
global dbuser
dbuser = imps_config['database']['user']
global dbpass
dbpass = imps_config['database']['password']
global IMPS_PATH
IMPS_PATH = imps_config['directories']['imps_path']
global BACKUP_DIR
BACKUP_DIR = imps_config['directories']['backup_dir']
global ITEM_IMAGE_DIR
ITEM_IMAGE_DIR = imps_config['directories']['item_image_dir']
global HELP_DIR
HELP_DIR = imps_config['directories']['help_dir']


########################################################################
### CONFIGURE SQL CONNECTION
########################################################################
try:
    mydb = sql_db.connect(host=dbhost, database=dbname, user=dbuser, password=dbpass)
    mydb.autocommit = True
except:
    print ("no db")

########################################################################
### CONFIGURE UPLOADS
########################################################################

UPLOAD_FOLDER = ITEM_IMAGE_DIR
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}

app.config["UPLOAD_FOLDER"] = "static/images/items/"


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

########################################################################
### HELP ROUTE
########################################################################
@app.route("/help")
def help():

    ## SHOW THE HELP INDEX
    response = make_response(
        render_template("help.html", HELP_DIR = HELP_DIR)
    )
    return response


########################################################################
### HOMEPAGE
########################################################################


@app.route("/")
def home():
    if os.path.isfile("first.run"):
        ## SET VARIABLES
        db_conn = "t"
        db_struct = "t"
        imps_path_config = "t"
        item_image_config = "t"
        backup_config = "t"

        ## TEST DB CONNECTION
        try:
            cursor = mydb.cursor(prepared=True)
            cursor.close()
        except:
            db_conn = "f"
        ## TEST DB TABLE

        try:
            ### SET UP QUERY
            test_query = "SELECT * FROM items"

            ### QUERY DB
            cursor = mydb.cursor()
            cursor.execute(test_query)
            result = cursor.fetchall()
            cursor.close()
        except:
            db_struct = "f"
        ## TEST PATHS
        if os.path.exists(IMPS_PATH):
               imps_path_config = imps_path_config
        else:
            imps_path_config = "f"
        if os.path.exists(IMPS_PATH + ITEM_IMAGE_DIR):
               item_image_config = item_image_config
        else:
            item_image_config = "f"
        if os.path.exists(BACKUP_DIR):
               backup_config = backup_config
        else:
            backup_config = "f"

        ## SHOW WELCOME PAGE
        return render_template("firstrun.html" ,
               db_conn=db_conn,
               db_struct = db_struct,
               imps_path_config = imps_path_config,
               item_image_config = item_image_config,
               backup_config = backup_config
               )
    else:
        ## SHOW THE HOME PAGE
        response = make_response(
            render_template("index.html", cookies=request.cookies)
        )
        return response


########################################################################
### SEARCH
########################################################################

### SEARCH TERM INPUT
@app.route("/search")
def search():

    ## SHOW THE SEARCH PAGE
    return render_template("search.html")


#################################################
### SWITCH SEARCH VIEW
@app.route("/search_view_switch", methods=["POST"])
def search_view_switch():

    global ITEM_IMAGE_DIR

    ### SEARCH ITEM NAMES
    query_term = (request.form["search-term"])
    item_query = """ SELECT * FROM items WHERE item_name LIKE CONCAT('%',?,'%')"""
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_query,(query_term,))
    result = cursor.fetchall()
    item_list1 = result
    cursor.close()


    ### SEARCH DESCRIPTION
    desc_query = "SELECT * FROM items WHERE item_desc LIKE CONCAT('%',?,'%')"
    cursor = mydb.cursor(prepared=True)
    cursor.execute(desc_query,(query_term,))
    result = cursor.fetchall()
    item_list2 = result
    cursor.close()

    set1 = (item_list1)
    set2 = (item_list2)
    item_list=list(set1.union(set2))

    ### FLIP THE VIEW COOKIE AND SHOW THE APPROPRIATE VIEW
    current_view = request.cookies.get("view")
    if current_view == "mobile":
        response = make_response(
            render_template(
                "search_result.html",
                search_term=query_term,
                item_list=result,
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            )
        )
        response.set_cookie("view", "desk")
        return response
    else:
        response = make_response(
            render_template(
                "search_result_mobile.html",
                search_term=query_term,
                item_list=item_list,
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            )
        )
        response.set_cookie("view", "mobile")
        return response


#################################################
### PERFORM SEARCH AND SHOW RESULTS
@app.route("/search_result", methods=["POST"])
def search_result():

    global ITEM_IMAGE_DIR
    ### SEARCH ITEM NAMES
    query_term = request.form["search-term"]
    query_statement = "SELECT * FROM items WHERE item_name LIKE CONCAT('%',?,'%')"
    cursor = mydb.cursor(prepared=True)
    cursor.execute(query_statement,(query_term,))
    result = cursor.fetchall()
    item_list1 = result
    cursor.close()

    ### SEARCH ITEM DESCR
    desc_query = "SELECT * FROM items WHERE item_desc LIKE CONCAT('%',?,'%')"
    cursor = mydb.cursor(prepared=True)
    cursor.execute(desc_query,(query_term,))
    result = cursor.fetchall()
    item_list2 = result
    cursor.close()

    ## MERGE RESULTS WITHOUT DUPLICATES
    set1 = (item_list1)
    set2 = (item_list2)
    item_list = list(set(set1)| set(set2))

    ### READ COOKIE AND SHOW APPROPRIATE VIEW
    current_view = request.cookies.get("view")
    if current_view == "mobile":
        response = make_response(
            render_template(
                "search_result_mobile.html",
                item_list=result,
                cookies=request.cookies,
                search_term=query_term,
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            )
        )
        return response
    else:
        response = make_response(
            render_template(
                "search_result.html",
                item_list=item_list,
                cookies=request.cookies,
                search_term=query_term,
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            )
        )
        return response


########################################################################
### SHOW ALL ITEMS / INVENTORY
########################################################################


@app.route("/inventory")
def inventory():

    global ITEM_IMAGE_DIR
    ### SET UP QUERY
    offset = 0
    limit = 30
    inv_query = """ SELECT * FROM items ORDER BY item_num LIMIT ? OFFSET ? """

    ### QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(inv_query,(limit,offset))
    result = cursor.fetchall()
    cursor.close()
    item_list = result

    ### GET COOKIE AND SHOW THE APPROPRAITE VIEW
    current_view = request.cookies.get("view")
    if current_view == "mobile":
        return render_template(
            "inventory_mobile.html",
            item_list=result,
            offset = offset,
            ITEM_IMAGE_DIR=ITEM_IMAGE_DIR
        )
    else:
        return render_template(
            "inventory.html",
            item_list=item_list,
            offset = offset,
            ITEM_IMAGE_DIR=ITEM_IMAGE_DIR
        )


#################################################
### SWITCH INVENTORY VIEW
@app.route("/inventory_view_switch")
def inventory_vs():

    global ITEM_IMAGE_DIR

    ### ALL ITEMS QUERY
    inv_query = "SELECT * FROM items"
    cursor = mydb.cursor()
    cursor.execute(inv_query)
    result = cursor.fetchall()
    cursor.close()

    ### GET COOKIE TO DETERMINE VIEW
    current_view = request.cookies.get("view")

    ### FLIP THE VIEW COOKIE AND SHOW THE APPROPRIATE VIEW
    if current_view == "mobile":
        response = make_response(
            render_template(
                "inventory.html",
                item_list=result,
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
                cookies=request.cookies,
            )
        )
        response.set_cookie("view", "desk")
        return response
    else:
        response = make_response(
            render_template(
                "inventory_mobile.html",
                item_list=result,
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
                cookies=request.cookies,
            )
        )
        response.set_cookie("view", "mobile")
        return response


########################################################################
### BOX INTERACTIONS
########################################################################


#################################################
### LIST OF ALL BOXES
@app.route("/boxlist")
def boxlist():

    ### QUERY FOR ALL BOXES
    allbox_query = "SELECT * FROM boxes"
    cursor = mydb.cursor()
    cursor.execute(allbox_query)
    result = cursor.fetchall()
    categories = result
    box_list = result

    ### QUERY FOR BOX NUMBERS OF BOXES THAT ARE NOT EMPTY
    not_empty_box_query = "SELECT box_num FROM items WHERE item_num >0 ORDER BY box_num;"
    cursor = mydb.cursor()
    cursor.execute(not_empty_box_query)
    result = cursor.fetchall()
    not_empty_list = result
    cursor.close()

    ## CREATE A LIST OF IN-USE BOX NUMBERS
    not_empty_box_num_list = []
    for i in not_empty_list:
        not_empty_box_num_list.append(i[0])

    ## ELIMINATE DUPLICATES
    not_empty_box_num_list = list(set(not_empty_box_num_list))

    ## SHOW THE LIST OF BOXES PAGE
    return render_template ("boxlist.html",
        box_list=box_list,
        not_empty_box_num_list = not_empty_box_num_list )


#################################################
### SELECT BOX TO VIEW BY NUMBER
@app.route("/bybox")
def bybox():

    global ITEM_IMAGE_DIR
    ### QUERY EXISTING BOX NUMBERS
    available_box_nums_query = "SELECT boxes.box_num FROM boxes;"
    cursor = mydb.cursor()
    cursor.execute(available_box_nums_query)
    result = cursor.fetchall()
    num_items = len(result)
    available_boxes = []
    cursor.close()

    ## TURN RESULT INTO A LIST
    for i in range(num_items):
        container = list(result[i])
        available_boxes.insert(1, container.pop())

    ### SHOW BOX SELECTION PAGE
    return render_template(
        "bybox.html",
	ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
	available_boxes=available_boxes
    )


#################################################
### SELECT BOX TO VIEW
@app.route("/bycategory")
def bycategory():

    global ITEM_IMAGE_DIR
    ### QUERY FOR ALL CATEGORIES
    all_cats_query = "SELECT cat_name FROM categories;"
    cursor = mydb.cursor()
    cursor.execute(all_cats_query)
    result = cursor.fetchall()
    num_cats = len(result)
    all_cats = []
    cursor.close()

    ## TURN RESULT INTO A LIST
    for i in range(num_cats):
        container = list(result[i])
        all_cats.insert(1, container.pop())

    ### QUERY ALL CATEGORIES
    used_cats_query = "SELECT item_cat FROM items;"
    cursor = mydb.cursor()
    cursor.execute(used_cats_query)
    result = cursor.fetchall()
    num_cats = len(result)
    used_cats = []
    cursor.close()

    ## TURN RESULT INTO A LIST
    for i in range(num_cats):
        container = list(result[i])
        used_cats.insert(1, container.pop())

    ## CREATE A LIST OF ONLY THOSE CATS WHICH CONTAIN ITEMS
    available_cats = list(set(all_cats).intersection(used_cats))
    ## SORT THE LIST
    available_cats = sorted(available_cats)

    ### SHOW BOX SELECTION PAGE
    return render_template(
        "bycategory.html",
        ITEM_IMAGE_DIR = ITEM_IMAGE_DIR,
        available_cats = available_cats
    )

#################################################
### BOX REDIRECT
@app.route("/boxredirect", methods=["POST"])
def boxredirect():
    box_num = request.form["box-num"]
    return render_template(
        "boxredirect.html", 
        box_num=box_num
    )


#################################################
### SWITCH BOX VIEW
@app.route("/boxviewswitch/<box_num>")
def box_view_switch(box_num):

    global ITEM_IMAGE_DIR

    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(box_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )


    ### BOX CONTENT QUERY
    query_box = box_num
    query_statement = """ SELECT * FROM items WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(query_statement, (query_box,))
    result = cursor.fetchall()
    item_list = result

    ### BOX NAME QUERY
    box_name_query = """ SELECT box_name FROM boxes WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(box_name_query,(query_box,))
    result = cursor.fetchone()
    box_name = result[0]

    cursor.close()

    ### FLIP THE VIEW COOKIE AND RETURN APPROPRIATE VIEW
    current_view = request.cookies.get("view")

    ### SHOW THE BOX CONTENT BASED ON VIEW
    if current_view == "mobile":
        response = make_response(
            render_template(
                "boxshowcontent.html",
                item_list=item_list,
                box_name=box_name,
                box_num=box_num,
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            )
        )
        response.set_cookie("view", "desk")
        return response
    else:
        response = make_response(
            render_template(
                "boxshowcontent_mobile.html",
                item_list=item_list,
                box_name = box_name,
                box_num = box_num,
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            )
        )
        response.set_cookie("view", "mobile")
        return response


#################################################
### DISPLAY BOX CONTENTS OF SELECTED BOX
@app.route("/boxshowcontent/<box_num>")
def showbox(box_num):

    global ITEM_IMAGE_DIR

    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(box_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ### BOX CONTENT QUERY
    query_box = box_num
    items_in_box_query = """ SELECT * FROM items WHERE box_num = ?  """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(items_in_box_query, (query_box,))
    result = cursor.fetchall()
    item_list = result

    ### EMPTY BOX VIEW IF THE SELECTED BOX HAS NO ITEMS
    if not result:
        return render_template(
            "errorpage.html",
            err_message="The selected box does not contain any items.",
            err_page_from="/bybox",
        )

    ### BOX NAME QUERY
    box_name_query = """ SELECT box_name FROM boxes WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(box_name_query,(query_box,))
    result = cursor.fetchone()
    box_name = result[0]
    cursor.close()

    current_view = request.cookies.get("view")

    ## SHOW THE BOX CONTENT PAGE BASED ON VIEW
    if current_view == "mobile":
        response = make_response(
            render_template(
                "boxshowcontent_mobile.html",
                item_list = item_list,
                box_name = box_name,
                box_num = box_num,
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            )
        )
        return response

    else:
        box_name = box_name
        response = make_response(
            render_template(
                "boxshowcontent.html",
                item_list = item_list,
                box_name = box_name,
                box_num = box_num,
                ITEM_IMAGE_DIR = ITEM_IMAGE_DIR,
            )
        )
        return response


#################################################
### CREATE AND SHOW BOX LABEL / QR CODE
@app.route("/boxlabel/<box_num>")
def boxlabel(box_num):

    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(box_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    query_box = box_num

    ### ASSIGN QR VARIBABLES
    qr_base_url = "http://192.168.0.100:88/boxshowcontent/"
    qr_url = qr_base_url + "/" + str(box_num)

    ### CALL QR LIBRARY TO MAKE THE QR IMAGE
    img = qrcode.make(qr_url)
    type(img)

    ### SAVE THE IMAGE
    save_location = "static/images/qrcodes/qr_code_for_box_" + str(box_num) + ".png"
    img.save(save_location)

    ### SET THE QR FILE LOCATION
    box_num_save_loc = [box_num, "/" + save_location]

    ### BOX NAME QUERY
    box_name_query = """ SELECT box_name FROM boxes WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(box_name_query, (query_box,))
    result = cursor.fetchone()
    cursor.close()
    box_name = result[0]

    ### SHOW THE LABEL
    return render_template(
        "boxprintlabel.html",
        box_num = box_num,
        box_num_save_loc = box_num_save_loc,
        box_name = box_name,
    )


#################################################
### ADD NEW BOX FORM
@app.route("/boxadd")
def boxadd():

    ### QUERY ALL CATEGORIES
    category_query = "SELECT * FROM categories"
    cursor = mydb.cursor()
    cursor.execute(category_query)
    result = cursor.fetchall()
    categories = result

    ### QUERY BOX NUMS CURRENTLY IN USE
    available_box_nums_query = "SELECT box_num FROM boxes ORDER BY box_num;"
    cursor = mydb.cursor()
    cursor.execute(available_box_nums_query)
    result = cursor.fetchall()
    box_nums = result
    cursor.close()

    ## TURN RESULT INTO A
    box_num_list = []
    for i in box_nums:
        box_num_list.append(i[0])
    box_nums = box_num_list

    ### FIND THE FIRST AVAILABLE BOX NUMBER
    first_available_box = None
    for i in range(len(box_nums) - 1):
        if box_nums[i + 1] - box_nums[i] > 1:
            first_available_box = box_nums[i] + 1
            break

    ### IF NO GAP ADD NEW BOX AT END OF
    if not first_available_box:
        first_available_box = len(box_nums) + 1

    ### SHOW THE ADD BOX PAGE
    return render_template(
        "boxadd.html",
        categories = categories,
        box_nums = box_nums,
        first_available_box = first_available_box
    )


#################################################
@app.route("/boxmoveitemsconf", methods=["POST"])
def boxmoveitems():
    ## GET VARIABLE FROM FORM PAGE
    old_box_num = request.form["box_to_del"]

    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(old_box_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ### QUERY BOX NUMBERS CURRENTLY IN USE
    available_box_nums_query = "SELECT box_num FROM boxes ORDER BY box_num;"
    cursor = mydb.cursor()
    cursor.execute(available_box_nums_query)
    result = cursor.fetchall()
    box_nums = result

    ### TURN RESULT INTO A LIST
    box_num_list = []
    for i in box_nums:
        box_num_list.append(i[0])
    box_nums = box_num_list

    ## SHOW THE PAGE
    return render_template(
        "boxmoveitemsconf.html",
        box_nums = box_nums,
        old_box_num = old_box_num
    )


#################################################
@app.route("/boxorphanitemsconf", methods=["POST"])
def boxorphanitems():
    ## GET VARIABLE FROM FORM PAGE
    box_to_del = request.form["box_to_del"]

    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(box_to_del)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ## QUERY BOX STATE
    box_state_query = """ SELECT * FROM items where box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(box_state_query, (box_to_del,))
    result = cursor.fetchall()
    if cursor.rowcount == 0:
        box_state = "empty"
    else:
        box_state = "not_empty"

    ## SHOW ORPHAN ITEMS PAGE
    return render_template(
        "boxorphanitemsconf.html",
        box_to_del = box_to_del,
        box_state = box_state
    )


#################################################
@app.route("/boxorphanitemssuccess", methods=["POST"])
def boxorphanitemssuccess():
    ## GET VARIABLE FROM FORM PAGE
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

    ## ORPHAN ITEMS QUERY
    query_box = box_to_del
    orphan_query = """ UPDATE items SET box_num = NULL WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(orphan_query,(query_box,))
    cursor.close()

    ## BOX DELETE QUERY
    box_del_query = """ DELETE FROM boxes WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(box_del_query,(query_box,))
    cursor.close()

    mydb.commit()

    return render_template(
        "boxorphanitemssuccess.html"
    )

#################################################
@app.route("/boxmoveitemssuccess", methods=["POST"])
def boxmoveitemssuccess():
    ## GET VARS FROM FORM PAGE
    box_to_del = request.form["box_to_del"]
    new_box_num = request.form["new_box_num"]

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_to_del) + int(new_box_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ## MOVE ITEMS TO NEW BOX QUERY
    move_query = """UPDATE items SET box_num = ? WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(move_query,(new_box_num,box_to_del))
    cursor.close()

    ## DELETE BOX QUERY
    box_del_query = """ DELETE FROM boxes WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(box_del_query,(query_del,))
    cursor.close()

    mydb.commit()

    return render_template(
        "boxmoveitemssuccess.html",
        new_box_num = new_box_num,
        deleted_box = box_to_del
    )



#################################################
### ADD BOX TO DB AND SHOW SUCCESS PAGE
@app.route("/boxadded", methods=["POST"])
def boxadded():

    if request.form["box_type"]=="next_available":
        box_num = request.form["next_num"]
    else:
        box_num = request.form["box_num"]

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )
    ## GET OTHER VARIABLES FROM FORM
    next_available_box_num = request.form["next_available_box_num"]
    box_cat = request.form["box_cat"]
    box_name = request.form["box_name"]
    box_type = request.form["box_type"]

    ## IF NO CATEGORY WAS SELECTED, SET TO UNCATEGORIZED
    if box_cat == None or box_cat == "":
        box_cat == "uncategorized"

    ## IF NEXT AVAIABLE IS SET, USE THAT BOX
    if box_type == "next_available":
        box_num = next_available_box_num

    ### QUERY CATGORY NAME
    category_query = "SELECT cat_name FROM categories"
    cursor = mydb.cursor()
    cursor.execute(category_query)
    result = cursor.fetchall()
    categories = result

    ## TURN RESULT INTO A LIST
    cat_list = []
    for i in categories:
        cat_list.append(i[0])
    categories = cat_list

    ### ADD CATEGORY TO DB IF NEW
    if box_cat not in categories:
        ### SET UP ADD CATEGORY QUERY
        add_cat_query = """ INSERT into categories (cat_name) VALUES (?) """
        query_cat = box_cat
        cursor = mydb.cursor(prepared=True)
        cursor.execute(add_cat_query,(box_cat,))
        mydb.commit()

    current_date = str(date.today())

    ### QUERY NEW BOX DATA
    query_vars=(box_num, box_cat, box_name, current_date, current_date)
    query_string = """ INSERT INTO boxes (box_num, box_cat, box_name, box_date, box_last_changed) VALUES\
    (?,?,?,?,?) """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(query_string, query_vars)
    mydb.commit()

    cursor.close()

    ### SHOW SUCCESS PAGE
    return render_template(
        "boxadded.html",
        box_num = box_num,
        box_cat = box_cat,
        box_name = box_name
    )


#################################################
### DELETE BOX
@app.route("/boxdel", methods=["POST","GET"])
def boxdel():

    ## IF CALLED FROM BOX LIST PAGE GET BOX NUMBER
    if request.method == "POST":
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
    else:
        box_to_del = ""

    ### QUERY BOX NUMBERS CURRENTLY IN USE
    available_box_nums_query = "SELECT box_num FROM boxes ORDER BY box_num;"
    cursor = mydb.cursor()
    cursor.execute(available_box_nums_query)
    result = cursor.fetchall()
    box_nums = result

    ### CREATE LIST FROM RESULT
    box_num_list = []
    for i in box_nums:
        box_num_list.append(i[0])
    box_nums = box_num_list

    ### QUERY BOX NUMBERS OF BOXES THAT ARE NOT EMPTY
    not_empty_box_query = (
        "SELECT box_num FROM items WHERE item_num >0 ORDER BY box_num;"
    )
    cursor = mydb.cursor()
    cursor.execute(not_empty_box_query)
    result = cursor.fetchall()
    not_empty_list = result
    cursor.close()

    ## TURN RESULT INTO A LIST
    not_empty_box_num_list = []
    for i in not_empty_list:
        not_empty_box_num_list.append(i[0])

    ## ELIMINATE DUPLICATES
    not_empty_box_num_list = list(set(not_empty_box_num_list))

    ## SHOW THE DEL BOX PAGE
    return render_template(
        "boxdel.html",
        box_nums = box_nums,
        not_empty_box_num_list = not_empty_box_num_list,
        box_to_del = box_to_del
    )


#################################################
### DELETE BOX CONFIRM PAGE
@app.route("/delboxconf", methods=["POST"])
def delboxconf():
    ## GET BOX NUMER FROM FORM VARIABLE
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

    ## GET ITEM HANDLING FROM FORM VARIABLE
    item_handling = request.form["item_handling"]

    ## CHECK IF BOX HAS CONTENTS
    box_state_query = """ SELECT * FROM items WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(box_state_query,(box_to_del,))
    result = cursor.fetchall()
    if cursor.rowcount == 0:
        box_state = "empty"
    else:
        box_state = "not_empty"

    ## SHOW THE BOX DELETE CONFIRMATION PAGE
    return render_template(
        "boxdelconfirm.html",
        box_state=box_state,
        box_to_del=box_to_del
    )


#################################################
### EDIT BOX FORM
@app.route("/boxedit")
def boxedit():
    ### SETUP AVAILABLE BOX NUMERS QUERY
    available_box_nums_query = "SELECT boxes.box_num FROM boxes;"

    ### QUERY DB
    cursor = mydb.cursor()
    cursor.execute(available_box_nums_query)
    result = cursor.fetchall()
    num_items = len(result)
    cursor.close()

    ## TURN RESULT INTO A LIST
    available_boxes = []
    for i in range(num_items):
        container = list(result[i])
        available_boxes.insert(1, container.pop())

    ### RETURN BOX SELECTION PAGE
    return render_template(
        "boxedit.html",
        available_boxes = available_boxes
    )


#################################################
### SHOW BOX DETAILS
@app.route("/boxdetails", methods=["POST"])
def boxdetails():
    ### SET UP BOX DETAILS QUERY
    box_num = request.form["box-num"]

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ## QUERY BOX
    box_details_query = """ SELECT * FROM boxes WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(box_details_query,(box_num,))
    result = cursor.fetchall()
    box_details = result

    ### QUERY ALL CATEGORIES
    category_query = "SELECT * FROM categories"
    cursor = mydb.cursor()
    cursor.execute(category_query)
    result = cursor.fetchall()
    categories = result
    cursor.close()

    ## ASSIGN VALUES TO FORM VARIABLES
    box_num = box_details[0][0]
    box_desc = box_details[0][2]
    box_cat = box_details[0][1]

    ## SHOW BOX DETAILS
    return render_template(
        "boxdetails.html",
        box_num=box_num,
        box_desc=box_desc,
        box_cat=box_cat,
        categories=categories,
    )


#################################################
### WRITE BOX CHANGES TO DB AND SHOW SUCCESS PAGE
@app.route("/boxeditsuccess", methods=["GET", "POST"])
def boxeditsuccess():
    ### GET VARS FROM FORM
    box_name = request.form["box_name"]
    box_cat = request.form["box_cat"]
    box_num = request.form["box_num"]

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ### BOX UPDATE QUERY
    query_name = box_name
    query_num = box_num
    if box_cat == "":
        box_update_query = """ UPDATE boxes SET box_name = ? WHERE box_num =  ? """

        ## QUERY DB
        cursor = mydb.cursor(prepared=True)
        cursor.execute(box_update_query,(query_name, query_num))
        cursor.close()
        mydb.commit()

    if box_cat != "":
        box_update_query = """ UPDATE boxes SET box_name = ? , box_cat = ? WHERE box_num = ? """

        ### QUERY DB
        cursor = mydb.cursor(prepared=True)
        cursor.execute(box_update_query,(query_name, box_cat, query_num))
        cursor.close()
        mydb.commit()

    ## ADD THE CATEGORY TO THE CAT TABLE IF IT DOESNT EXIST

    ### QUERY FOR CATEGORIES
    category_query = "SELECT cat_name FROM categories"
    cursor = mydb.cursor()
    cursor.execute(category_query)
    result = cursor.fetchall()
    categories = result

    ## TURN RESULT INTO A LIST
    cat_list = []
    for i in categories:
        cat_list.append(i[0])
    categories = cat_list

    ### CHECK SUBMITTED CATEGORY AGAINST DB LIST
    if box_cat not in categories and box_cat != "":
        ### SET UP ADD CATEGORY QUERY
        add_cat_query = """ INSERT into categories (cat_name) VALUES (?) """
        cursor = mydb.cursor(prepared=True)
        cursor.execute(add_cat_query, (box_cat,))
        mydb.commit()

    ## SHOW SUCESS PAGE
    return render_template(
        "boxeditedsuccess.html",
        box_name = box_name,
        box_cat = box_cat,
        box_num = box_num
    )


#################################################
### DELETE BOX FROM DB AND SHOW SUCCESS PAGE
@app.route("/boxdeletesuccess/<box_to_del>")
def boxdeletesuccess(box_to_del):

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(box_to_del)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ### QUERY TO DELETE BOX
    query_box = box_to_del
    del_box_query = """DELETE FROM boxes WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(del_box_query, (query_box,))
    mydb.commit()

    ### QUERY TO DELETE ITEMS
    del_items_query = """ DELETE FROM items WHERE box_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(del_items_query,(query_box,))
    mydb.commit()
    cursor.close()

    ## SHOW BOX DELETE SUCCESS PAGE
    return render_template(
        "boxdelsuccess.html",
        box_to_del=box_to_del
    )


########################################################################
### ITEM MANAGMENT
########################################################################


#################################################
### SHOW THE ADD ITEM FORM
@app.route("/itemadd")
def itemadd():

    ### SET UP QUERY FOR CATEGORIES
    category_query = "SELECT * FROM categories"

    ### QUERY BD
    cursor = mydb.cursor()
    cursor.execute(category_query)
    result = cursor.fetchall()
    available_categories = result

    ### SET UP QUERY FOR AVAILABLE BOXES
    available_box_nums_query = "SELECT boxes.box_num FROM boxes;"

    ### QUERY DB
    cursor = mydb.cursor()
    cursor.execute(available_box_nums_query)
    result = cursor.fetchall()

    cursor.close()

    num_items = len(result)
    available_boxes = []

    ## CONVERT RESULT TO LIST
    for i in range(num_items):
        container = list(result[i])
        available_boxes.insert(1, container.pop())

    ### SHOW ITEM ADD PAGE

    return render_template(
        "itemadd.html",
        categories = available_categories,
        available_boxes = available_boxes
    )

#################################################
### EDIT ITEM FORM
@app.route("/itemedit/<item_num>")
def itemedit(item_num):

    global ITEM_IMAGE_DIR

    ### VERIFY VARIABLE IS AN INT
    try:
        check_int = int(item_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ### SET UP ITEM DB QUERY
    query_item = item_num
    item_query_statement = """ SELECT * FROM items WHERE item_num = ? """

    ### QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_query_statement,(item_num,))
    result = cursor.fetchall()
    item_result = result

    ### SET UP CATEGORY DB QUERY
    category_query_statement = "SELECT * FROM categories;"

    ### QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(category_query_statement)
    result = cursor.fetchall()
    categories = result

    ### SET UP QUERY FOR AVAILABLE BOXES
    available_box_nums_query = "SELECT boxes.box_num FROM boxes;"

    ### QUERY DB
    cursor = mydb.cursor()
    cursor.execute(available_box_nums_query)
    result = cursor.fetchall()

    cursor.close()

    num_items = len(result)
    available_boxes = []

    ## CHANGE RESULT NEW LIST
    for i in range(num_items):
        container = list(result[i])
        available_boxes.insert(1, container.pop())

    available_boxes.sort()

    ### RETURN RESULTS PAGE
    return render_template(
        "itemedit.html",
        item_result = item_result,
        categories = categories,
        available_boxes = available_boxes,
        ITEM_IMAGE_DIR = ITEM_IMAGE_DIR
    )


#################################################
### SUBMIT EDITED ITEM DETAILS
@app.route("/updateitem/<item_num>", methods=["POST"])
def updateitem(item_num):

    global ITEM_IMAGE_DIR

    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ## GET VALUES FROM FORM DATA
    ud_item_num = item_num
    ud_item_date = request.form["item_date"]
    ud_item_name = request.form["item_name"]
    ud_item_desc = request.form["item_desc"]
    ud_box_num = request.form["box_num"]
    ud_item_cat = request.form["item_cat"]
    ud_passed_in_cat = request.form["passed_in_cat"]

    ## HANDLE CATEGORY DATAFIELD NOT CHANGED
    if ud_item_cat == "":
        ud_item_cat = ud_passed_in_cat

    ##SET UP ITEM DB QUERY
    item_update_query = """UPDATE items SET item_name = ?, item_desc = ?, item_cat = ?, item_date = ?,\
        box_num = ? WHERE item_num = ? """

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_update_query,(ud_item_name, ud_item_desc,ud_item_cat,ud_item_date,ud_box_num, ud_item_num) )
    mydb.commit()

    cursor.close()

    ################################
    ## CHECK THAT CATEGORY IS IN DB

    ## SET UP CATEGORY DB QUERY
    category_query_statement = "SELECT * FROM categories;"

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(category_query_statement)
    result = cursor.fetchall()
    categories = result

    ## CHANGE RESULT TO A LIST
    cat_list = []
    for i in categories:
        cat_list.append(i[0])
    categories = cat_list

    ## CHECK SUBMITTED CATEGORY AGAINST DB LIST
    ## AND ADD TO DB IF NOT
    if ud_item_cat not in categories:
        ### SET UP ADD CATEGORY QUERY
        add_cat_query = """ INSERT into categories (cat_name) VALUES (?) """
        cursor = mydb.cursor(prepared=True)
        cursor.execute(add_cat_query, (ud_item_cat,))
        mydb.commit()

    ## SET UP QUERY TO SHOW ITEM
    item_query = """ SELECT item_pic FROM items WHERE item_num = ? """

    ### DB QUERY
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_query,(item_num,))
    result = cursor.fetchone()
    cursor.close()

    item_pic = result[0]

    ## SHOW ITEM PAGE
    return render_template(
        "itemdetail.html",
        item_name = ud_item_name,
        item_num = ud_item_num,
        box_num = ud_box_num,
        item_date = ud_item_date,
        item_cat = ud_item_cat,
        item_desc = ud_item_desc,
        item_pic = item_pic,
        ITEM_IMAGE_DIR = ITEM_IMAGE_DIR
    )


#################################################
### ADD ITEM TO DB AND UPLOAD AND SAVE PHOTO
@app.route("/iteminsert", methods=["POST"])
def iteminsert():

    photoincluded = request.form["photo_yes_no"]

    if request.method == "POST" and photoincluded == "yes":
        # check that the post request contains a file
        if 'file' not in request.files:
            return render_template('errorpage.html', err_message = "The photo did not load.", err_page_from ="/")

        file = request.files["file"]
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == "":
            return render_template(
                "errorpage.html",
                err_message="No file selected",
                err_page_from="/itemaddphoto",
            )

        ## IF THE FILE IS ALLOWED AND IN THE POST, SAVE IT
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)

            ## TIMESTAMP THE FILENAME TO HANDEL DUPES
            pp = pathlib.PurePath(filename)
            filename = pp.stem + str(time.time()) + pp.suffix
            save_path = IMPS_PATH + ITEM_IMAGE_DIR +  filename
            file.save(save_path)

        ## IF THE FILE IS PROHIBITED SHOW ERROR PAGE
        else:
            return render_template(
                "errorpage.html",
                err_message="That file type is not allowed.",
                err_page_from="/photoadded",
            )
    else:
        filename = ""
    ### GET DATE
    current_date = str(date.today())

    # get the filename and path
    item_name = request.form["item_name"]
    box_num = request.form["box_num"]
    item_cat = request.form["item_cat"]
    item_desc = request.form["item_desc"]

    if item_cat == "":
        item_cat = "uncategorized"

    if filename == "":
         item_pic = "none.jpg"
    else:
         item_pic = filename

    ## SET UP QUERY TO INSERT ITEM
    insert_query = """ INSERT INTO items (item_name, box_num, item_pic, item_date, item_cat, item_desc) \
         VALUES ( ?, ?, ?, ?, ?, ?) """

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(insert_query,(item_name, box_num, item_pic, current_date, item_cat, item_desc))
    mydb.commit()
    cursor.close()

    ## GET THE ITEM NUMBER OF THE ITEM ADDED
    last_item_query = "SELECT LAST_INSERT_ID();"
    cursor = mydb.cursor(prepared=True)
    cursor.execute(last_item_query)
    result = cursor.fetchone()
    cursor.close()

    item_num = result[0]

    ### SET UP THE QUERY FOR CATEGORIES
    category_query = "SELECT cat_name FROM categories"

    ### QUERY DB
    cursor = mydb.cursor()
    cursor.execute(category_query)
    result = cursor.fetchall()
    categories = result

    ## CHANGE RESULT TO A LIST
    cat_list = []
    for i in categories:
        cat_list.append(i[0])
    categories = cat_list

    ### CHECK SUBMITTED CATEGORY AGAINST DB LIST
    if item_cat not in categories:
        ### SET UP ADD CATEGORY QUERY
        add_cat_query = """ INSERT into categories (cat_name) VALUES (?) """
        cursor = mydb.cursor(prepared=True)
        cursor.execute(add_cat_query, (item_cat,))
        mydb.commit()

    ## SHOW THE ADD PHOTO PAGE
    return showitemdetail(str(item_num))

#################################################
### SHOW THE UPDATE PHOTO FORM
@app.route("/itemupdatephoto/<item_num>")
def itemupdatephoto(item_num):

    ### VERIFY ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )


    item_name_query = """ SELECT item_name FROM items WHERE item_num = ? """

    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_name_query, (item_num,))
    result = cursor.fetchone()
    cursor.close()

    item_name = result[0]

    item_file_name_query = (
        """ SELECT item_pic FROM items WHERE item_num = ? """
    )
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_file_name_query, (item_num,))
    result = cursor.fetchone()
    cursor.close()

    item_pic = result[0]

    return render_template(
        "itemupdatephoto.html",
        item_name=item_name,
        item_num=item_num,
        item_pic=item_pic,
    )


############################################################
## UPLOAD UPDATED PHOTO AND SHOW SUCCESS FORM
@app.route("/photoupdated", methods=["POST"])
def photoupdated():

    ### GET VARIABLE FROM FORM
    item_num = request.form["item_num"]

    ### CHECK THAT VARIABLE IS AN INT
    try:
        check_int = int(item_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )


    if request.method == "POST":
        # check that the post request contains a file
        if 'file' not in request.files:
            return render_template('errorpage.html', err_message = "The photo did not load.", err_page_from ="/")

        file = request.files["file"]
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == "":
            return render_template(
                "errorpage.html",
                err_message="No file selected",
                err_page_from="/itemaddphoto",
            )

        ## IF THE FILE IS ALLOWED AND IN THE POST, SAVE IT
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)

            ## ADD TIMESTAMP TO FILE NAME TO HANDLE DUPES
            pp = pathlib.PurePath(filename)
            filename = pp.stem + str(time.time()) + pp.suffix
            save_path = IMPS_PATH + ITEM_IMAGE_DIR +  filename
            file.save(save_path)
        ## IF THE FILE IS PROHIBITED SHOW ERROR PAGE
        else:
            return render_template(
                "errorpage.html",
                err_message="That file type is not allowed.",
                err_page_from="/photoadded",
            )

    ## SET UP PIC QUERY
    item_pic = filename
    pic_query =  """ UPDATE items set item_pic = ? WHERE item_num = ?"""

    ## INSERT FILENAME INTO DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(pic_query,(item_pic, item_num))
    mydb.commit()

    cursor.close()

    ## SET UP QUERY FOR ADDED ITEM
    added_item_query = """ SELECT * FROM items WHERE item_num = ? """

    ### QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(added_item_query, (item_num,))
    result = cursor.fetchall()
    cursor.close()

    ### SHOW RESULTS PAGE
    return render_template(
        "itemedit.html",
        item_result=result,
        ITEM_IMAGE_DIR = ITEM_IMAGE_DIR
    )


#################################################
## UPLOAD NEW PHOTO AND SHOW SUCCESS FORM
@app.route("/photoadded", methods=["POST"])
def photoadded():

    if request.method == "POST":
        # check that the post request contains a file
        if 'file' not in request.files:
            return render_template('errorpage.html', err_message = "The photo did not load.", err_page_from ="/")

        file = request.files["file"]
        # If the user does not select a file, the browser submits an
        # empty file without a filename.
        if file.filename == "":
            return render_template(
                "errorpage.html",
                err_message="No file selected",
                err_page_from="/itemaddphoto",
            )

        ## IF THE FILE IS ALLOWED AND IN THE POST, SAVE IT
        if file and allowed_file(file.filename):
            filename = secure_filename(file.filename)

            ## HANDLE DUPES
            pp = pathlib.PurePath(filename)
            filename = pp.stem + str(time.time()) + pp.suffix

            save_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(save_path)
        ## IF THE FILE IS PROHIBITED SHOW ERROR PAGE
        else:
            return render_template(
                "errorpage.html",
                err_message="That file type is not allowed.",
                err_page_from="/photoadded",
            )

    ## SET UP ITEM NUMBER QUERY
    query_statement = "SELECT LAST_INSERT_ID();"

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(query_statement)
    result = cursor.fetchone()
    cursor.close()

    ## CONSTRUCT THE QUERY
    item_num = str(result[0])
    pic_query = """ UPDATE items set item_pic = ? WHERE item_num = ? """

    ## INSERT FILENAME INTO DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(query_statement, (filename, item_num))
    mydb.commit()

    cursor.close()

    ## SET UP QUERY FOR ADDED ITEM
    query_statement = """ SELECT * FROM items WHERE item_num = ? """

    ### QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(query_statement,(item_num,))
    result = cursor.fetchall()

    cursor.close()

    ### SHOW RESULTS PAGE
    return render_template(
        "itemdetail.html",
        item_result=result
    )


#################################################
### ITEM SUCCESSFULLY ADDED
@app.route("/addeditem", methods=["POST"])
def addeditem():
    ## ITEM_NUM FROM UPLOAD PAGE
    item_num = request.form["item_num"]

    ### CHECK THAT VARIABLE IS AN INT
    try:
        check_int = int(item_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    item_query = """ SELECT * FROM items WHERE item_num = ? """
    ### DB QUERY
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_query,(item_num,))
    result = cursor.fetchall()
    cursor.close()
    ### RETURN RESULTS PAGE
    return render_template(
        "search_result.html",
        search_result=result
    )


##############################################
## ITEM DETAIL PAGE (NOT EDITABLE)
@app.route("/showitemdetail/<item_num>")
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

    item_query = """ SELECT * FROM items WHERE item_num = ? """
    ### DB QUERY
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_query,(item_num,))
    result = cursor.fetchone()

    cursor.close()

    item_result = result

    item_num = item_result[0]
    item_name = item_result[1]
    box_num = item_result[2]
    item_pic = item_result[3]
    item_date = item_result[4]
    item_cat = item_result[5]
    item_desc = item_result[6]

    ### RETURN RESULTS PAGE
    return render_template(
        "itemdetail.html",
        item_name=item_name,
        item_num=item_num,
        item_pic=item_pic,
        box_num=box_num,
        item_date=item_date,
        item_cat=item_cat,
        item_desc=item_desc,
        ITEM_IMAGE_DIR = ITEM_IMAGE_DIR
    )


########################################################################
### SHOW ALL ITEMS IN A CATEGORY

@app.route("/itemsbycategory", methods=["POST"])
def itembycategory():

    global ITEM_IMAGE_DIR
    ### SET UP QUERY
    cat_name = request.form["category"]
    item_by_cat_query = """ SELECT * FROM items WHERE item_cat = ? """

    ### QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_by_cat_query,(cat_name,))
    result = cursor.fetchall()
    cursor.close()

    print(result)

    if cursor.rowcount == 0:
        return render_template(
            "errorpage.html",
            err_message="There no are items in this category",
            err_page_from="/bycategory",
        )

    item_list = result

    ### GET COOKIE AND SHOW THE APPROPRAITE VIEW
    current_view = request.cookies.get("view")
    if current_view == "mobile":
        return render_template(
            "itemsbycat_mobile.html",
            item_list=result,
            ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            cat_name=cat_name,
        )
    else:
        return render_template(
            "itemsbycat.html",
            item_list=item_list,
            ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            cat_name=cat_name,
        )


#################################################
### SWITCH ITEMS BY CAT VIEW
@app.route("/itemsbycat_view_switch/<cat_name>")
def itemsbycat_view_switch(cat_name):

    global ITEM_IMAGE_DIR
    ### SET UP QUERY
    item_by_cat_query = """ SELECT * FROM items WHERE item_cat = ? """

    ### QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_by_cat_query,(cat_name,))
    result = cursor.fetchall()
    cursor.close()
    item_list = result

    ### FLIP THE VIEW COOKIE AND SHOW THE APPROPRIATE VIEW
    current_view = request.cookies.get("view")
    if current_view == "mobile":
        response = make_response(
            render_template(
                "itemsbycat.html",
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
                cat_name=cat_name,
                item_list=item_list,
            )
        )
        response.set_cookie("view", "desk")
        return response
    else:
        response = make_response(
            render_template(
                "itemsbycat_mobile.html",
                ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
                cat_name=cat_name,
                item_list=result,
            )
        )
        response.set_cookie("view", "mobile")
        return response


###########################################
## DELETE ITEM PAGE
@app.route("/itemdel/<item_num>")
def itemdel(item_num):

    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    del_query = """ SELECT * FROM items WHERE item_num = ? """

    ### DB QUERY
    cursor = mydb.cursor(prepared=True)
    cursor.execute(del_query,(item_num,))
    result = cursor.fetchall()
    cursor.close()
    ### RETURN RESULTS PAGE
    return render_template(
        "itemdel.html",
        item_result=result
    )


###########################################
@app.route("/itemdeleted/<item_to_del>")
def itemdeleted(item_to_del):

    global ITEM_IMAGE_DIR

    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(item_to_del)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ## SET UP PHOTO FILE NAME QUERY STATEMENT
    photo_file_query = """ SELECT item_pic FROM items WHERE item_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(photo_file_query,(item_to_del,))
    result = cursor.fetchone()

    ## CREATE VARIABLES FOR FILE DELETION
    photo_dir = ITEM_IMAGE_DIR[1:]
    photo_filename = result[0]
    photo_file = photo_dir + result[0]

    ## DELETE PHOTO UNLESS IT IS THE PLACEHOLDER
    delete_failed = False
    if photo_filename != "none.jpg":
        try:
            os.remove(photo_file)
        except:
            delete_failed = True

    ## GET ITEM NAME FOR RESULTS PAGE
    item_name_query = """ SELECT item_name FROM items WHERE item_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(item_name_query,(item_to_del,))
    result = cursor.fetchone()
    item_name = result[0]


    ## SET UP DELETE STATEMENT
    del_query = """ DELETE FROM items WHERE item_num = ? """

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(del_query, (item_to_del,))
    result = cursor.fetchall()

    cursor.close()
    ## RETURN SUCCESS
    if delete_failed == True:
        return render_template(
            "errorpage.html",
            err_message="The item was deleted from the database,\
                but IMPS was unable to delete image photo file.",
            err_page_from="/",
        )
    else:
        return render_template(
            "itemdelconfirm.html",
            item_name=item_name
        )


########################################################################
### CONTROL PANEL
########################################################################


###########################################
@app.route("/control_panel")
def controlpanel():
    global dbhost
    global dbname
    global dbuser
    global dbpass
    global ITEM_IMAGE_DIR
    global BACKUP_DIR

    ## SET UP BACKUP QUERY
    backup_query = "SELECT value FROM `settings` WHERE name ='backup_filename'; "

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(backup_query)
    result = cursor.fetchone()
    backup_loc = result[0]

    ## SET UP BACKUP QUERY
    backup_query = "SELECT value FROM `settings` WHERE name ='last_backup'; "

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(backup_query)
    result = cursor.fetchone()
    last_backup = result[0]

    cursor.close

    return render_template(
        "control_panel.html",
        backup_loc=backup_loc,
        backup_date=last_backup,
        dbhost=dbhost,
        dbname=dbname,
        dbuser=dbuser,
        dbpass=dbpass,
        ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
        BACKUP_DIR=BACKUP_DIR,
    )


###########################################
@app.route("/cp_dbbackup")
def cp_dbbackup():
    ## START BACKUP PROCESS
    global BACKUP_DIR
    BACKUP_DIR = "/var/www/html/static/backup"
    backup_time = str(time.time())

    dumpcmd = (
        "mysqldump -u "
        + dbuser
        + " -p"
        + dbpass
        + " "
        + dbname
        + " > "
        + BACKUP_DIR
        + "/"
        + dbname
        + "-"
        + backup_time
        + ".sql"
    )

    os.system(dumpcmd)
    backup_file = "/static/backup/" + dbname + "-" + backup_time + ".sql"

    ## SET UP BACKUP DATE QUERY
    today = str(date.today())
    backup_date_query = (
        ''' UPDATE settings SET value="''' + today + """" WHERE set_num = "2"; """
    )

    cursor = mydb.cursor(prepared=True)
    cursor.execute(backup_date_query)
    mydb.commit()

    cursor.close

    ## SET UP UP CATEGORIES QUERY
    backup_query = """SELECT value FROM `settings` WHERE name ='backup_filename'; """

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(backup_query)
    result = cursor.fetchone()

    return render_template("cp_dbbackup.html", backup_file=backup_file)


###########################################
@app.route("/cp_categories")
def cp_categories():

###################################################################################
    ## SET UP UP CATEGORIES QUERY
    cat_name_num_query = "SELECT cat_name, cat_num FROM categories ORDER BY cat_name;"

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(cat_name_num_query)
    result = cursor.fetchall()
    num_items = len(result)
    cat_name_num = result

    ## CREATE A LIST FROM RESULT
    all_cat_nums = []
    for i in range(num_items):
        container = list(result[i])
        all_cat_nums.insert(1, container.pop())

    ## SET UP UP CATEGORIES QUERY
    category_query = "SELECT cat_name FROM categories ORDER BY cat_name;"

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(category_query)
    result = cursor.fetchall()
    num_items = len(result)
    all_categories = result

    ## CREATE A LIST FROM RESULT
    all_categories = []
    for i in range(num_items):
        container = list(result[i])
        all_categories.insert(1, container.pop())

    ## SETP UP ITEM PER CAT QUERY
    cats_with_items_query = "SELECT item_cat, COUNT(1) FROM items GROUP BY item_cat;"
    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(cats_with_items_query)
    result = cursor.fetchall()
    cats_with_items = result
    cursor.close()

    items_per_cat=[]

    counter = -1
    for category in all_categories:
        assigned = False
        counter = counter + 1
        for item_cat in cats_with_items:
            if item_cat[0] == category:
                tuple = (category,item_cat[1],all_cat_nums[counter])
                items_per_cat.append(tuple)
                assigned = True
        if not assigned:
            tuple = (category, 0,all_cat_nums[counter])
            items_per_cat.append(tuple)

#    items_per_cat.sort(key=lambda items_per_cat: items_per_cat[0])

    ## RETURN SUCCESS
    return render_template(
        "cp_categories.html",
        items_per_category=items_per_cat
    )


########################################################################
@app.route("/cp_photofilescleanup")
def cp_photofilescleanup():

    global ITEM_IMAGE_DIR

    ## SET UP PHOTO QUERY
    photo_files_query = "SELECT item_pic  FROM items;"

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(photo_files_query)
    result = cursor.fetchall()
    file_names_in_db = result

    cursor.close()

    num_items = len(result)
    item_list = []
    ## ITERATE THROUGH RESULT AND CONCATENATE NEW LIST
    for i in range(num_items):
        container = list(result[i])
        item_list.insert(1, container.pop())

    item_list.sort()

    files_in_dir = []
    files_in_dir =   os.listdir("/var/www/html"+ITEM_IMAGE_DIR)
    files_in_dir.sort()

    orphans = list(set(files_in_dir).difference(item_list))

    return render_template(
        "cp_photofilescleanup.html",
        file_names_in_db = item_list,
        orphans = orphans,
        ITEM_IMAGE_DIR = ITEM_IMAGE_DIR,
    )

########################################################################
@app.route("/cp_editcat/<cat_num>")
def cp_editcat(cat_num):

    ## SET UP CATEGORY QUERY
    category_query = """ SELECT cat_name  FROM categories WHERE cat_num = ? """

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(category_query,(cat_num,))
    result = cursor.fetchone()
    cat_name = result[0]
    cursor.close()


    return render_template(
        "cp_catedit.html",
        cat_name = cat_name,
        cat_num = cat_num
    )

########################################################################
@app.route("/cp_cateditsuccess/<cat_num>", methods=["POST"])
def cp_cateditsuccess(cat_num):

    cat_num = request.form["cat_num"]
    cat_name = request.form["cat_name"]


    ## SET UP CATEGORY QUERY
    update_cat_query = "UPDATE categories SET cat_name ='" + cat_name + "' WHERE cat_num =" + cat_num + ";"

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(update_cat_query)
    mydb.commit()
    cursor.close()

    return cp_categories()

########################################################################
@app.route("/cp_delcat/<cat_num>")
def cp_catdel(cat_num):


    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(cat_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ## SET UP CATEGORY QUERY
    category_query = """ SELECT cat_name  FROM categories WHERE cat_num = ? """

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(category_query,(cat_num,))
    result = cursor.fetchone()
    cat_name = result[0]
    cursor.close()


    return render_template(
        "cp_catdelconf.html",
        cat_name = cat_name,
        cat_num = cat_num
    )

########################################################################
@app.route("/cp_catdelsuccess/<cat_num>", methods=["POST"])
def cp_catdelsuccess(cat_num):

    ### CHECK THAT ROUTE DECORATOR IS AN INT
    try:
        check_int = int(cat_num)
    except:
        return render_template(
            "errorpage.html",
            err_message="Entry is not a number.",
            err_page_from="/",
        )

    ## GET CATEGORY NAME
    get_cat_query = """ SELECT cat_name FROM categories WHERE cat_num = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(get_cat_query,(cat_num,))
    result = cursor.fetchone()
    cat_name = result[0]

    ## REASSIGN ITEMS
    update_item_cat_query = """ UPDATE items SET item_cat ='uncategorized' WHERE item_cat = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(update_item_cat_query,(cat_name,))
    mydb.commit()

    ## REASSIGN BOX CATEGORIES
    update_box_cat_query = """ UPDATE boxes SET box_cat ='uncategorized' WHERE box_cat = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(update_box_cat_query,(cat_name,))
    mydb.commit()

    ## DELETE CATEGORY
    del_cat_query = """ DELETE FROM categories WHERE cat_name = ? """
    cursor = mydb.cursor(prepared=True)
    cursor.execute(del_cat_query,(cat_name,))
    mydb.commit()
    cursor.close()

    ## RETURN TO CATEGORY LIST PAGE
    return cp_categories()

########################################################################
@app.route("/cp_delallorphans")
def cp_delallorphans():
    global ITEM_IMAGE_DIR

########################################################################
@app.route("/cp_addcat", methods=["POST"])
def cp_addcat():
    global ITEM_IMAGE_DIR
    new_cat = request.form["new_cat"]

    ## SET UP ADD CATEGORY QUERY
    add_cat_query = """ INSERT INTO categories (cat_num, cat_name) VALUES (NULL, ?) """

    ## QUERY DB
    cursor = mydb.cursor(prepared=True)
    cursor.execute(add_cat_query,(new_cat,))
    mydb.commit()
    cursor.close()

    ## RETURN TO CATEGORY LIST PAGE
    return cp_categories()

########################################################################
### MAIN LOOP
########################################################################

if __name__ == "__main__":

    app.run(host="0.0.0.0", port=88, debug=True)
