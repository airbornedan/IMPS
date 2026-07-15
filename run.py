########################################################################
### ENTRY POINT
########################################################################
# Run with:  python run.py
# (For production, run with gunicorn instead, e.g.:
#    gunicorn -w 4 -b 0.0.0.0:80 'run:app')

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=88, debug=False)
