########################################################################
### APPLICATION FACTORY
########################################################################
import os
import re
import ipaddress

from flask import Flask, request, session

from app.extensions import ITEM_IMAGE_DIR, FLASK_SECRET_KEY, csrf, limiter
from app import extensions

########################################################################
### "LAST LIST VIEW" TRACKING
########################################################################
# Every endpoint below renders includeitemlist.html (or its mobile
# variant) somewhere, i.e. every page the item-delete button can be
# clicked from. Recording the current URL here -- server-side, in the
# session -- lets itemdel()/itemdeleted() offer a reliable "back to
# where you were" link without depending on the browser's Referer
# header, which is dropped inconsistently by proxies, CDNs, privacy
# extensions, and some default Referrer-Policy settings even for
# same-origin navigation.
LIST_VIEW_ENDPOINTS = {
    "main.search_result",
    "inventory.inventory",
    "inventory.showbox",
    "items.itembycategory",
    "control_panel.cp_orphan_list",
    "control_panel.orphan_vs",
}


def create_app():
    # template_folder/static_folder point back to the project root so the
    # existing templates/ and static/ directories don't need to move.
    app = Flask(__name__, template_folder="../templates", static_folder="../static")

    # SECRET_KEY is generated once at first run and persisted to a file
    # outside of source control (see app/extensions.py) instead of being
    # hard-coded here, so it can't be read out of the repo/source.
    app.config["SECRET_KEY"] = FLASK_SECRET_KEY
    app.config["UPLOAD_FOLDER"] = ITEM_IMAGE_DIR

    ####################################################################
    ### OPTIONAL LAN-ONLY ACCESS RESTRICTION
    ####################################################################
    # Off unless explicitly enabled via [access] restrict_to_lan = true
    # (with a valid lan_ip) in imps_config.toml -- see extensions.py's
    # _load_lan_restriction() for the parsing, and
    # imps_config.toml.example for the config format and the
    # Docker/reverse-proxy caveat. Deliberately simple: reject anything
    # outside the derived home-network range, no exceptions list, no
    # X-Forwarded-For handling -- this only makes sense for IMPS talking
    # to clients directly (the plain Apache/mod_wsgi deploy).
    @app.before_request
    def enforce_lan_restriction():
        if not extensions.LAN_RESTRICTION_ENABLED:
            return None
        try:
            remote = ipaddress.ip_address(request.remote_addr)
        except (TypeError, ValueError):
            return ("Forbidden.", 403)
        if remote not in extensions.LAN_NETWORK:
            return ("Forbidden.", 403)
        return None

    ####################################################################
    ### STATIC FILE CACHING
    ####################################################################
    # Without this, Flask's static handler only sets an ETag/
    # Last-Modified, so the browser still issues a conditional GET (and
    # waits on a 304 response) for every static asset -- including the
    # header logo -- on every single page navigation, since this app
    # does a full page reload on every link click. That round trip is
    # what was showing up as a visible flash/repaint of the logo.
    #
    # A max-age here lets the browser skip asking the server entirely
    # for repeat views within this window, instead of just skipping
    # the download. Kept fairly short (1 hour) rather than the usual
    # far-future value, since static/help/*.html is being actively
    # hand-edited right now -- a long cache would mean edited help
    # pages don't show up in the browser until it expires or the page
    # gets a hard refresh. Once help content settles down this can be
    # raised (a day, a week) for a bit more benefit on the rarely
    # changing assets (logo, icons, CSS/JS).
    app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 3600

    ####################################################################
    ### SESSION COOKIE HARDENING
    ####################################################################
    app.config["SESSION_COOKIE_HTTPONLY"] = True       # JS can't read the cookie
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"       # blocks cross-site form/script submits
    # Only force Secure cookies once actually served over HTTPS -- forcing
    # this on over plain HTTP means the browser will silently refuse to
    # send the cookie at all, locking everyone out. Flip IMPS_HTTPS=1 once
    # behind TLS (e.g. behind an nginx reverse proxy terminating SSL).
    app.config["SESSION_COOKIE_SECURE"] = os.environ.get("IMPS_HTTPS", "0") == "1"
    app.config["SESSION_COOKIE_NAME"] = "imps_session"  # don't advertise "this is Flask"
    app.config["PERMANENT_SESSION_LIFETIME"] = 60 * 60 * 8  # 8 hours, if session is ever made permanent

    ####################################################################
    ### CSRF PROTECTION
    ####################################################################
    csrf.init_app(app)

    ####################################################################
    ### RATE LIMITING
    ####################################################################
    limiter.init_app(app)

    # Importing extensions here (above) also triggers config/db_pool setup
    # via app/extensions.py the first time it's imported.

    ####################################################################
    ### CONTEXT-SENSITIVE HELP
    ####################################################################
    # Derives a stable "topic" name from the current route so templates
    # can point the help panel's iframe at
    # /static/help/imps_<help_topic>_help.html without every route
    # having to set this itself. URL variables (<box_num>, <item_num>,
    # etc.) are stripped out first since the *route* is the help topic,
    # not whichever particular box/item/category happened to be in the
    # URL -- e.g. /boxshowcontent/4 and /boxshowcontent/17 both resolve
    # to the same "boxshowcontent" topic.
    @app.context_processor
    def inject_help_topic():
        topic = "home"
        if request.url_rule:
            rule = re.sub(r"<[^>]+>", "", request.url_rule.rule)
            topic = rule.strip("/").replace("/", "_") or "home"
        return {"help_topic": topic}

    ####################################################################
    ### "LAST LIST VIEW" TRACKING (see LIST_VIEW_ENDPOINTS above)
    ####################################################################
    @app.after_request
    def remember_list_view(response):
        # Not restricted to GET: showbox (and potentially other list
        # views) is registered for both GET and POST, and box_num etc.
        # live in the URL path rather than the POST body, so
        # request.path is a complete, safe representation of the view
        # either way.
        if (
            request.endpoint in LIST_VIEW_ENDPOINTS
            and response.status_code == 200
        ):
            path = request.path
            if request.query_string:
                path += "?" + request.query_string.decode("utf-8")
            session["last_list_view"] = path
        return response

    from app.blueprints.auth import bp as auth_bp
    from app.blueprints.main import bp as main_bp
    from app.blueprints.setup import bp as setup_bp
    from app.blueprints.inventory import bp as inventory_bp
    from app.blueprints.boxes import bp as boxes_bp
    from app.blueprints.items import bp as items_bp
    from app.blueprints.control_panel import bp as control_panel_bp
    from app.blueprints.help import bp as help_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(boxes_bp)
    app.register_blueprint(items_bp)
    app.register_blueprint(control_panel_bp)
    app.register_blueprint(help_bp)

    return app
