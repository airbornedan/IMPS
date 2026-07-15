#!/usr/bin/env python3
########################################################################
### IMPS DB DOWN MONITOR
########################################################################
# Standalone script, NOT part of the Flask app -- runs on its own via
# a systemd timer (see imps-db-monitor.timer). Checks whether the
# database is reachable, and emails once if it's been continuously
# down for at least DOWN_THRESHOLD_MINUTES, and once more when it
# recovers. Does NOT attempt to restart anything -- alerting only.
#
# Given the check interval this is normally run at (every 30 min, per
# the timer), you'll typically hear about an outage on the SECOND
# consecutive failed check -- i.e. after roughly one full interval,
# not precisely DOWN_THRESHOLD_MINUTES. That's fine for a low-stakes
# hobby project; if you want tighter timing later, shorten the timer
# interval rather than this threshold.
#
# SETUP (one-time):
#   1. In your Google account: create an "app password" for Gmail
#      (requires 2-factor auth enabled on the account) --
#      https://myaccount.google.com/apppasswords
#   2. Copy mail_credentials.toml.example to mail_credentials.toml,
#      fill in your Gmail address, the app password, and where you
#      want alerts sent. chmod 600 it, same as reset_credentials.toml.
#   3. Test manually: python3 db_monitor.py --test-email
#      (sends a test email immediately, bypassing the down-check, so
#      you can confirm SMTP creds work without waiting for a real
#      outage)
#   4. Wire up the systemd timer (imps-db-monitor.service / .timer).
########################################################################

import argparse
import os
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage

import toml
import mysql.connector

########################################################################
### CONFIG -- adjust for your install
########################################################################

APP_CONFIG_FILE = "/var/www/getimps.com/demo/imps_config.toml"        # read-only: reuses box_user's own DB creds, nothing new needed
MAIL_CONFIG_FILE = "/var/www/getimps.com/demo/deploy/mail_credentials.toml"
STATE_FILE = "/var/www/getimps.com/demo/deploy/.db_monitor_state.toml"

DOWN_THRESHOLD_MINUTES = 20
CONNECT_TIMEOUT_SECONDS = 5  # fail fast -- this is a health check, not a real query


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def load_toml(path, label):
    if not os.path.isfile(path):
        raise SystemExit(f"{label} not found: {path}")
    mode = os.stat(path).st_mode & 0o777
    if mode & 0o077:
        log(f"  WARNING: {path} is readable/writable by group or others (mode {oct(mode)}). Run: chmod 600 {path}")
    return toml.load(path)


def check_db_reachable():
    app_cfg = load_toml(APP_CONFIG_FILE, "App config")
    db_cfg = app_cfg["database"]
    try:
        conn = mysql.connector.connect(
            host=db_cfg["host"],
            user=db_cfg["user"],
            password=db_cfg["password"],
            database=db_cfg["name"],
            connection_timeout=CONNECT_TIMEOUT_SECONDS,
        )
        conn.ping(reconnect=False)
        conn.close()
        return True, None
    except Exception as e:
        return False, str(e)


def send_email(subject, body):
    mail_cfg = load_toml(MAIL_CONFIG_FILE, "Mail config")["mail"]

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_cfg["from_address"]
    msg["To"] = mail_cfg["to_address"]
    msg.set_content(body)

    context = ssl.create_default_context()
    with smtplib.SMTP(mail_cfg.get("smtp_host", "smtp.gmail.com"), mail_cfg.get("smtp_port", 587)) as server:
        server.starttls(context=context)
        server.login(mail_cfg["from_address"], mail_cfg["app_password"])
        server.send_message(msg)


def load_state():
    if not os.path.isfile(STATE_FILE):
        return {}
    try:
        return toml.load(STATE_FILE)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        toml.dump(state, f)


def clear_state():
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)


def main():
    parser = argparse.ArgumentParser(description="Check IMPS DB connectivity and email on prolonged outage.")
    parser.add_argument("--test-email", action="store_true", help="Send a test email immediately and exit, bypassing the actual DB check.")
    args = parser.parse_args()

    if args.test_email:
        send_email(
            "IMPS DB monitor -- test email",
            "This is a test email from the IMPS DB monitor script. If you're reading this, SMTP credentials are working correctly.",
        )
        log("Test email sent.")
        return

    reachable, error_detail = check_db_reachable()
    state = load_state()

    if reachable:
        if state.get("alert_sent"):
            # We previously alerted that it was down -- let them know it's back.
            down_since = state.get("first_failure_at", "unknown time")
            send_email(
                "IMPS DB back up",
                f"The IMPS database is reachable again.\n\nIt had been down since approximately {down_since} (server time).",
            )
            log("DB is back up -- recovery email sent.")
        else:
            log("DB reachable. No action needed.")
        clear_state()
        return

    # DB is not reachable right now.
    now = time.time()
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    if "first_failure_at" not in state:
        # First failed check -- just record it, don't alert yet.
        state = {"first_failure_at": now_str, "first_failure_epoch": now, "alert_sent": False}
        save_state(state)
        log(f"DB unreachable ({error_detail}). First failure recorded, not yet past threshold.")
        return

    elapsed_minutes = (now - state.get("first_failure_epoch", now)) / 60

    if elapsed_minutes >= DOWN_THRESHOLD_MINUTES and not state.get("alert_sent"):
        send_email(
            "IMPS DB DOWN",
            (
                f"The IMPS database has been unreachable for at least {int(elapsed_minutes)} minutes.\n\n"
                f"First detected down at: {state['first_failure_at']} (server time)\n"
                f"Last error: {error_detail}\n\n"
                f"This is an alert only -- nothing was restarted automatically."
            ),
        )
        state["alert_sent"] = True
        save_state(state)
        log(f"DB down for {int(elapsed_minutes)} min, past threshold -- alert email sent.")
    else:
        log(f"DB still unreachable ({error_detail}). Down for {int(elapsed_minutes)} min, threshold is {DOWN_THRESHOLD_MINUTES} min, alert_sent={state.get('alert_sent')}.")


if __name__ == "__main__":
    main()
