########################################################################
### ENTRY POINT
########################################################################
# Run with:  python run.py
# (For production, run with gunicorn instead, e.g.:
#    gunicorn -w 4 -b 0.0.0.0:80 'run:app')
# or via Apache. See deploy/apache/APACHE.md for instructions
#
# FLASK_DEBUG=1 enables Flask's debug mode and the startup checks in
# app/dev_checks.py.
import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "").lower() in ("1", "true", "yes")
    app.run(host="0.0.0.0", port=88, debug=debug)
