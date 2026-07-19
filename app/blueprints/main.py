########################################################################
### MAIN BLUEPRINT — LANDING PAGE, WELCOME/SETUP WIZARD, SEARCH
########################################################################
from flask import Blueprint, request, render_template, redirect, url_for, make_response, session
import os
import re

from flask_paginate import Pagination, get_page_parameter

from app.extensions import (
    get_db_connection,
    login_required,
    IMPS_DIR,
    ITEM_IMAGE_DIR,
    logger,
    db_errors,
    get_items_per_page,
    get_offset_for_page,
    InvalidPageError,
)
from app.sample_data import install_sample_data

bp = Blueprint("main", __name__)


@bp.route("/welcome")
def welcome():
    ### KEPT AS A THIN REDIRECT FOR OLD BOOKMARKS/MUSCLE MEMORY -- the
    ### full status page (DB + directories, both split into their own
    ### tables) now lives at setup.setup_landing, which is also where
    ### home() sends first-time visitors (see below).
    return redirect(url_for("setup.setup_landing"))


########################################################################
### FINISH FIRST-RUN SETUP: RENAME first.run, OPTIONALLY SEED SAMPLE DATA
########################################################################
@bp.route("/del_firstrun", methods=["GET", "POST"])
def del_firstrun():
    first_run = os.path.join(IMPS_DIR, "first.run")
    not_first_run = os.path.join(IMPS_DIR, "not_first.run")

    ### IF THE "INSTALL SAMPLE ITEMS" CHECKBOX WAS SUBMITTED, SEED DATA
    ### BEFORE RENAMING first.run. Nothing in the current UI posts to
    ### this route anymore -- the setup wizard's own setup_samples()/
    ### setup_password() (app/blueprints/setup.py) now handle sample
    ### data and finishing setup directly. Kept here, still functional,
    ### only for old bookmarks/direct hits; a plain GET (or a POST
    ### without the checkbox) just renames first.run with no sample
    ### data, same as the original behavior.
    if request.method == "POST" and request.form.get("install_samples"):
        try:
            install_sample_data()
        except Exception as e:
            logger.error(f"Sample data installation failed: {e}")
            return render_template(
                "errorpage.html",
                err_message="Could not install sample data. Check the server logs, "
                "or finish setup without it by visiting /del_firstrun directly.",
                err_page_from="/welcome",
            )

    try:
        os.rename(first_run, not_first_run)
    except OSError:
        print("File first.run already deleted")

    return redirect(url_for("main.home"))


########################################################################
### HOME PAGE
########################################################################
@bp.route("/")
def home():
    ####################################################################
    ### IF THIS IS THE INITAL RUN OF IMPS, TEST SETTINGS
    ### Uses the same absolute IMPS_DIR-based location del_firstrun()
    ### writes to (see above), rather than a bare relative "first.run"
    ### -- a relative path here only works if the process's current
    ### working directory happens to equal IMPS_DIR (true under
    ### adapter.wsgi, which os.chdir()s there explicitly, but not
    ### guaranteed under every possible way of starting the app).
    ### THIS MUST RUN BEFORE THE LOGIN CHECK BELOW -- a fresh install
    ### has no session yet, so gating this behind @login_required (as
    ### before) sent every first-time visitor to the login page
    ### instead of the setup wizard, since decorators run before any
    ### code in the function body.
    if os.path.isfile(os.path.join(IMPS_DIR, "first.run")):
        return redirect(url_for("setup.setup_landing"))

    ####################################################################
    ### NOT FIRST RUN -- NORMAL LOGIN GATE
    if not session.get("loggedin"):
        return redirect(url_for("auth.login"))

    ####################################################################
    ### OTHERWISE SHOW THE HOME PAGE
    else:
        response = make_response(render_template("index.html", cookies=request.cookies))
        return response


########################################################################
### SEARCH
########################################################################


########################################################################
### SEARCH TERM INPUT
@bp.route("/search")
@login_required
def search():
    ### SHOW THE SEARCH PAGE
    return render_template("search.html")


########################################################################
### PERFORM SEARCH AND SHOW RESULTS
@bp.route("/search_result/<query_term>")
@login_required
@db_errors(
    conn_msg="Database error when accessing inventory. Could not connect.",
    exec_msg="Database error when retrieving data.",
)
def search_result(query_term):
    #####################################
    ############# PAGINATION
    limit = get_items_per_page()
    try:
        offset = get_offset_for_page(limit)
    except InvalidPageError:
        return render_template(
            "errorpage.html",
            err_message="That page number doesn't exist.",
            err_page_from="/search",
        )
    ########################################################################

    # Fetch an active, thread-safe connection from the pool
    with get_db_connection() as mydb:
        ##############################################################
        ### BUILD A FUZZY, WORD-BY-WORD SEARCH
        ##############################################################
        # Splits the query into individual words, and matches an item
        # if it contains ANY of those words in ANY searchable
        # column (item_name / item_desc / item_cat). Each matching
        # word/column adds to a relevance score so items matching
        # more words (or matching in the name vs. the description)
        # rank higher, while still surfacing partial matches instead
        # of requiring every word to hit.
        #
        # SOUNDEX is also added as a phonetic fallback against
        # item_name, so a typo like "lamq" or "lampp" still surfaces
        # items named "lamp" -- true typo tolerance, not just substring
        # matching, with no extra DB extensions required.
        search_words = [w for w in re.split(r"\s+", query_term.strip()) if w]
        if not search_words:
            search_words = [query_term]

        where_clauses = []
        where_params = []
        score_clauses = []
        score_params = []
        for word in search_words:
            like_param = f"%{word}%"
            where_clauses.append(
                "(item_name LIKE %s OR item_desc LIKE %s OR item_cat LIKE %s "
                "OR SOUNDEX(item_name) = SOUNDEX(%s))"
            )
            where_params.extend([like_param, like_param, like_param, word])

            # Name matches count for more than description/category
            # matches, and an exact phonetic match counts a little
            # extra too, so the most relevant items bubble to the top.
            score_clauses.append(
                "(item_name LIKE %s)*3 + (item_desc LIKE %s) + "
                "(item_cat LIKE %s)*2 + (SOUNDEX(item_name) = SOUNDEX(%s))*2"
            )
            score_params.extend([like_param, like_param, like_param, word])

        where_sql = " OR ".join(where_clauses)
        score_sql = " + ".join(score_clauses)

        ### SET UP SEARCH QUERY : SEARCH ITEM NAMES, DESCRIPTIONS, AND CATEGORIES
        # The relevance score is computed in ORDER BY only (not SELECTed)
        # so the result tuples stay exactly 7 columns wide -- templates
        # like includeitemlist.html unpack each row positionally
        # (item_num, item_name, box_num, item_pic, item_date, item_cat,
        # item_desc) and would break if an extra column were added.
        # LIMIT/OFFSET are applied in SQL rather than fetching every
        # matching row and slicing to the current page in Python --
        # the previous version pulled the entire matching result set
        # (including item_desc text) across the wire on every search,
        # even though only `limit` rows of it were ever displayed.
        item_query = f""" SELECT * FROM items
                           WHERE {where_sql}
                           ORDER BY ({score_sql}) DESC, item_num DESC
                           LIMIT %s OFFSET %s """

        cursor = mydb.cursor()
        cursor.execute(item_query, tuple(where_params + score_params + [limit, offset]))
        result = cursor.fetchall()
        item_list = result
        cursor.close()

        ### GET NUMBER OF RESULTS (same WHERE clause, for pagination)
        num_item_query = f""" SELECT COUNT(*) FROM items WHERE {where_sql} """
        cursor = mydb.cursor()
        cursor.execute(num_item_query, tuple(where_params))
        result = cursor.fetchone()
        cursor.close()
        total = result[0]

    #####################################
    ############# PAGINATION
    search = False

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

    ### READ COOKIE AND SHOW APPROPRIATE VIEW
    ### (search_result.html branches internally on current_view)
    current_view = request.cookies.get("view")
    response = make_response(
        render_template(
            "search_result.html",
            current_view=current_view,
            item_list=item_list,
            page=page,
            pagination=pagination,
            cookies=request.cookies,
            search_term=query_term,
            ITEM_IMAGE_DIR=ITEM_IMAGE_DIR,
            info_column=info_column,
            photo_column=photo_column,
            date_column=date_column,
            cat_column=cat_column,
            box_column=box_column,
        )
    )
    return response
