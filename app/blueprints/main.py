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
    get_available_boxes,
    get_available_cats,
    ITEM_COVER_PHOTO_SELECT,
    ITEM_COVER_PHOTO_JOIN,
)
from app.sample_data import install_sample_data

bp = Blueprint("main", __name__)


@bp.route("/welcome")
def welcome():
    ### THIN REDIRECT, for old bookmarks/muscle memory -- the full
    ### status page (DB + directories, each in its own table) lives at
    ### setup.setup_landing, also where home() sends first-time
    ### visitors (see below).
    return redirect(url_for("setup.setup_landing"))


########################################################################
### FINISH FIRST-RUN SETUP: RENAME first.run, OPTIONALLY SEED SAMPLE DATA
########################################################################
@bp.route("/del_firstrun", methods=["GET", "POST"])
def del_firstrun():
    first_run = os.path.join(IMPS_DIR, "first.run")
    not_first_run = os.path.join(IMPS_DIR, "not_first.run")

    ### GUARD: ONLY REACHABLE DURING FIRST-RUN SETUP.
    ### Deliberately no @login_required here -- a fresh install has no
    ### usable password yet, same reasoning as every route in setup.py
    ### (see that file's module docstring / _guard()). Gating on
    ### first.run's presence instead gives the same effect: once setup
    ### has finished and first.run is renamed away, this route stops
    ### doing anything for anyone, logged in or not, rather than
    ### staying open forever as an unauthenticated way to re-seed
    ### sample data into a live inventory.
    if not os.path.isfile(first_run):
        return redirect(url_for("main.home"))

    ### IF THE "INSTALL SAMPLE ITEMS" CHECKBOX WAS SUBMITTED, SEED DATA
    ### BEFORE RENAMING first.run. The setup wizard's own
    ### setup_samples()/setup_password() (app/blueprints/setup.py)
    ### handle sample data and finishing setup directly; this route
    ### stays functional for old bookmarks/direct hits. A plain GET (or
    ### a POST without the checkbox) just renames first.run with no
    ### sample data.
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
        logger.info("first.run already removed.")

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
    ### has no session yet, so gating this behind @login_required would
    ### send every first-time visitor to the login page instead of the
    ### setup wizard, since decorators run before any code in the
    ### function body.
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
        # Splits the query into individual words, matches an item if it
        # contains ANY of those words in ANY searchable column
        # (item_name / item_desc / category name / location name), or
        # is a whole-number word matching the item's box number
        # exactly. Each matching word/column adds to a relevance score
        # so items matching more words (or matching in the name vs.
        # the description) rank higher, while still surfacing partial
        # matches instead of requiring every word to hit.
        #
        # SOUNDEX also covers item_name/category/location, for typo
        # tolerance ("lamq" -> "lamp"). Not item_desc -- SOUNDEX codes
        # a whole string as one value, useless against prose.
        search_words = [w for w in re.split(r"\s+", query_term.strip()) if w]
        if not search_words:
            search_words = [query_term]

        where_clauses = []
        where_params = []
        score_clauses = []
        score_params = []
        for word in search_words:
            like_param = f"%{word}%"
            if word.isdigit():
                where_clauses.append(
                    "(i.item_name LIKE %s OR i.item_desc LIKE %s OR "
                    "c.cat_name LIKE %s OR loc.loc_name LIKE %s OR "
                    "i.box_num = %s OR SOUNDEX(i.item_name) = SOUNDEX(%s) OR "
                    "SOUNDEX(c.cat_name) = SOUNDEX(%s) OR "
                    "SOUNDEX(loc.loc_name) = SOUNDEX(%s))"
                )
                where_params.extend(
                    [like_param, like_param, like_param, like_param, int(word),
                     word, word, word]
                )

                # Name matches count for more than description/category/
                # location matches, and an exact phonetic or box-number
                # match counts a little extra too, so the most relevant
                # items bubble to the top.
                score_clauses.append(
                    "(i.item_name LIKE %s)*3 + (i.item_desc LIKE %s) + "
                    "(c.cat_name LIKE %s)*2 + (loc.loc_name LIKE %s)*2 + "
                    "(i.box_num = %s)*2 + (SOUNDEX(i.item_name) = SOUNDEX(%s))*2 + "
                    "(SOUNDEX(c.cat_name) = SOUNDEX(%s))*2 + "
                    "(SOUNDEX(loc.loc_name) = SOUNDEX(%s))*2"
                )
                score_params.extend(
                    [like_param, like_param, like_param, like_param, int(word),
                     word, word, word]
                )
            else:
                where_clauses.append(
                    "(i.item_name LIKE %s OR i.item_desc LIKE %s OR "
                    "c.cat_name LIKE %s OR loc.loc_name LIKE %s OR "
                    "SOUNDEX(i.item_name) = SOUNDEX(%s) OR "
                    "SOUNDEX(c.cat_name) = SOUNDEX(%s) OR "
                    "SOUNDEX(loc.loc_name) = SOUNDEX(%s))"
                )
                where_params.extend(
                    [like_param, like_param, like_param, like_param, word, word, word]
                )

                score_clauses.append(
                    "(i.item_name LIKE %s)*3 + (i.item_desc LIKE %s) + "
                    "(c.cat_name LIKE %s)*2 + (loc.loc_name LIKE %s)*2 + "
                    "(SOUNDEX(i.item_name) = SOUNDEX(%s))*2 + "
                    "(SOUNDEX(c.cat_name) = SOUNDEX(%s))*2 + "
                    "(SOUNDEX(loc.loc_name) = SOUNDEX(%s))*2"
                )
                score_params.extend(
                    [like_param, like_param, like_param, like_param, word, word, word]
                )

        where_sql = " OR ".join(where_clauses)
        score_sql = " + ".join(score_clauses)

        ### SET UP SEARCH QUERY : SEARCH ITEM NAMES, DESCRIPTIONS,
        ### CATEGORIES, LOCATIONS, AND BOX NUMBERS
        # items.cat_num is a numeric foreign key rather than a string,
        # so categories has to be joined in to search/display the
        # category name -- c.cat_name is aliased as item_cat and rows
        # are fetched with a dict cursor, so includeitemlist.html (and
        # every other consumer) reads fields by name (row['item_cat'])
        # rather than by column position. See ITEMS_WITH_CAT_NAME in
        # items.py for the same convention. Relevance score is
        # computed in ORDER BY only (not SELECTed), so it doesn't need
        # a dict key here.
        # boxes/locations are LEFT JOINed, not JOINed -- an orphaned
        # item (box_num IS NULL) still needs to match on name/desc/
        # category, not be silently dropped from every search just
        # because it has no box to resolve a location through.
        # LIMIT/OFFSET are applied in SQL rather than fetching every
        # matching row and slicing to the current page in Python --
        # keeps only `limit` rows (including item_desc text) crossing
        # the wire per search, not the entire matching result set.
        item_query = f""" SELECT i.item_num, i.item_name, i.box_num, {ITEM_COVER_PHOTO_SELECT}, i.item_date,
                                  c.cat_name AS item_cat, i.item_desc
                           FROM items i
                           JOIN categories c ON i.cat_num = c.cat_num
                           LEFT JOIN boxes b ON i.box_num = b.box_num
                           LEFT JOIN locations loc ON b.loc_num = loc.loc_num
                           {ITEM_COVER_PHOTO_JOIN}
                           WHERE {where_sql}
                           ORDER BY ({score_sql}) DESC, i.item_num DESC
                           LIMIT %s OFFSET %s """

        cursor = mydb.cursor(dictionary=True)
        cursor.execute(item_query, tuple(where_params + score_params + [limit, offset]))
        result = cursor.fetchall()
        item_list = result
        cursor.close()

        ### GET NUMBER OF RESULTS (same WHERE clause, for pagination)
        num_item_query = f""" SELECT COUNT(*) FROM items i
                               JOIN categories c ON i.cat_num = c.cat_num
                               LEFT JOIN boxes b ON i.box_num = b.box_num
                               LEFT JOIN locations loc ON b.loc_num = loc.loc_num
                               WHERE {where_sql} """
        cursor = mydb.cursor()
        cursor.execute(num_item_query, tuple(where_params))
        result = cursor.fetchone()
        cursor.close()
        total = result[0]

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
            available_boxes=get_available_boxes(),
            available_cats=get_available_cats(),
        )
    )
    return response
