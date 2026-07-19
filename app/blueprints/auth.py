########################################################################
### AUTH BLUEPRINT — LOGIN / LOGOUT
########################################################################
from flask import Blueprint, request, render_template, redirect, url_for, make_response, session
import bcrypt

from app import extensions
from app.extensions import limiter

bp = Blueprint("auth", __name__)


@bp.route("/login")
def login():
    # Optional: If they are already logged in, send them straight to the index
    if session.get("loggedin"):
        return redirect("/")

    ### SHOW THE LOGIN PAGE
    response = make_response(
        render_template(
            "usr_login.html",
            logged_in=False,
        )
    )
    return response

@bp.route("/attemptlogin", methods=["POST"])
# Throttle login attempts per source IP. IMPS has a single shared
# password with no per-user lockout, so this is the main defense against
# brute-forcing it. 10/minute allows for normal typos while making
# sustained guessing impractical; the daily cap blocks slow/distributed
# attempts that try to stay under the per-minute threshold.
@limiter.limit("10 per minute; 100 per day")
def attemptlogin():
    userPassword = request.form.get("password")

    ### A MALFORMED/INCOMPLETE POST (e.g. a stale cached page, a
    ### replayed/bookmarked request) can arrive with no "password"
    ### field at all -- request.form["password"] would raise an
    ### unhandled KeyError (a generic Flask 400 page) in that case, so
    ### use .get() and handle it explicitly with IMPS's own error page.
    if not userPassword:
        return render_template(
            "errorpage.html",
            err_message="No password was submitted.",
            err_page_from="/login",
        )

    ### MATCH AGAINST PASS SET IN imps_config.toml
    ### (read via the extensions module, not a bare imported name, so
    ### a password change made through the setup wizard -- which calls
    ### extensions.reload_config() -- takes effect immediately here,
    ### rather than needing a process restart)
    userBytes = userPassword.encode("utf-8")
    pass_match = bcrypt.checkpw(userBytes, extensions.HASHED_IMPS_PASS)

    if pass_match == True:
        session["loggedin"] = True
        return redirect("/")
    else:
        return redirect(url_for("auth.loginfailed"))

########################################################################
###LOGOUT PAGE

@bp.route("/logout")
def logout():
    session.clear()
    response = make_response(
        render_template(
            "usr_logout.html",
            logged_in=False,
        )
    )
    return response

########################################################################
###LOGIN FAILED

@bp.route("/loginfailed")
def loginfailed():
    response = make_response(
        render_template(
            "usr_loginfailed.html",
            logged_in=False,
        )
    )
    return response
