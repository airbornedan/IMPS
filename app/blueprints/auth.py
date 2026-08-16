########################################################################
### AUTH BLUEPRINT — LOGIN / LOGOUT
########################################################################
from flask import Blueprint, request, render_template, redirect, url_for, make_response, session
import bcrypt

from app import extensions
from app.extensions import (
    limiter,
    login_backoff_seconds_remaining,
    login_backoff_record_failure,
    login_backoff_record_success,
    login_failure_note_for_logging,
    safe_relative_url,
)

bp = Blueprint("auth", __name__)


@bp.route("/login")
def login():
    ### WHERE TO SEND THEM BACK TO AFTER LOGGING IN -- set by
    ### login_required() when it bounced them here. Client-supplied
    ### (a query param), so treat it as untrusted -- same reasoning as
    ### back_url in the delete-item flows.
    next_url = safe_relative_url(request.args.get("next"))

    # Optional: If they are already logged in, send them straight to
    # where they were headed (or the index, if nowhere in particular).
    if session.get("loggedin"):
        return redirect(next_url or "/")

    ### SHOW THE LOGIN PAGE
    response = make_response(
        render_template(
            "usr_login.html",
            logged_in=False,
            next=next_url,
        )
    )
    return response

@bp.route("/attemptlogin", methods=["POST"])
# Throttle login attempts per source IP. IMPS has a single shared
# password with no per-user lockout, so this is the main defense
# against brute-forcing it. 10/minute allows normal typos while making
# sustained guessing impractical; the daily cap blocks slow/distributed
# attempts staying under the per-minute threshold.
#
# This flat limit is a hard ceiling; login_backoff_* (extensions.py)
# below is a second, softer layer that kicks in earlier -- each
# consecutive failure from an IP doubles its wait before the next
# attempt is even checked, so a sustained guessing run slows down
# well before reaching this per-minute/per-day cutoff.
@limiter.limit("10 per minute; 100 per day")
def attemptlogin():
    remote_ip = request.remote_addr

    ### EXPONENTIAL BACKOFF CHECK -- if this IP has failed recently,
    ### make it wait rather than checking the password again
    ### immediately. Doesn't consume/reset the flat rate limit above;
    ### the two are independent layers.
    wait_seconds = login_backoff_seconds_remaining(remote_ip)
    if wait_seconds > 0:
        return render_template(
            "errorpage.html",
            err_message=(
                "Too many failed login attempts. Please wait "
                f"{int(wait_seconds) + 1} second(s) and try again."
            ),
            err_page_from="/login",
        )

    user_password = request.form.get("password")

    ### A MALFORMED/INCOMPLETE POST (stale cached page, replayed/
    ### bookmarked request) can arrive with no "password" field at all
    ### -- request.form["password"] would raise an unhandled KeyError
    ### (a generic Flask 400) in that case, so use .get() and handle it
    ### explicitly with IMPS's own error page.
    if not user_password:
        return render_template(
            "errorpage.html",
            err_message="No password was submitted.",
            err_page_from="/login",
        )

    ### MATCH AGAINST PASS SET IN imps_config.toml
    ### (read via the extensions module, not a bare imported name, so a
    ### password change through the setup wizard -- which calls
    ### extensions.reload_config() -- takes effect immediately, no
    ### process restart needed)
    user_bytes = user_password.encode("utf-8")
    pass_match = bcrypt.checkpw(user_bytes, extensions.HASHED_IMPS_PASS)

    if pass_match:
        login_backoff_record_success(remote_ip)
        session["loggedin"] = True
        ### RE-VALIDATE next HERE TOO -- IT ARRIVED AS A POST BODY
        ### FIELD FROM THE CLIENT, SO TREAT IT AS UNTRUSTED EVEN THOUGH
        ### login() ALREADY SANITIZED IT ONCE.
        next_url = safe_relative_url(request.form.get("next"))
        return redirect(next_url or "/")
    else:
        login_backoff_record_failure(remote_ip)
        login_failure_note_for_logging(remote_ip)
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
