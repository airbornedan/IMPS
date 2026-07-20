########################################################################
### HELP BLUEPRINT — SEARCH OVER static/help/imps_*_help.html
########################################################################
# The help panel's search box (templates/includes/header.html,
# static/help_panel.js) calls GET /help/search?q=... and expects a
# JSON list of {topic, title, snippet}.
#
# The corpus here is small and static (46 short files, only ever
# changed by hand-editing them in static/help/) so this deliberately
# does the simplest thing that can't go stale: read the files fresh
# from disk into an in-memory list, cached at module scope, and
# substring-match against title + body text. No build step, no search
# index file to remember to regenerate -- whatever's on disk right
# now is what gets searched.
import os
import re

from flask import Blueprint, jsonify, request

from app.extensions import login_required

bp = Blueprint("help", __name__)

HELP_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "static", "help")
HELP_DIR = os.path.normpath(HELP_DIR)

# {topic: {"title": ..., "text": ...}}, populated on first request and
# reused after that. Since help files are only ever edited by hand
# during development (not by the running app), there's no need to
# re-scan on every request -- just once per process. Restart the app
# (or, during a dev session, hit /help/reload) to pick up edits.
_INDEX = None

# Matches the same "topic" naming used by app/__init__.py's
# inject_help_topic() and the file-naming convention described in the
# help README: imps_<topic>_help.html
_FILENAME_RE = re.compile(r"^imps_(.+)_help\.html$")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_tags(html):
    text = _TAG_RE.sub(" ", html)
    text = text.replace("&mdash;", "-").replace("&ndash;", "-")
    text = text.replace("&quot;", '"').replace("&amp;", "&")
    return _WS_RE.sub(" ", text).strip()


def _extract_title(html, fallback):
    m = re.search(r'class="help-heading">([^<]*)<', html)
    return m.group(1).strip() if m else fallback


def _build_index():
    index = {}
    if not os.path.isdir(HELP_DIR):
        return index
    for fname in os.listdir(HELP_DIR):
        m = _FILENAME_RE.match(fname)
        if not m:
            continue
        topic = m.group(1)
        try:
            with open(os.path.join(HELP_DIR, fname), encoding="utf-8") as f:
                raw = f.read()
        except OSError:
            continue
        title = _extract_title(raw, topic)
        text = _strip_tags(raw)
        index[topic] = {"title": title, "text": text}
    return index


def _get_index():
    global _INDEX
    if _INDEX is None:
        _INDEX = _build_index()
    return _INDEX


def _snippet(text, query, radius=60):
    lower = text.lower()
    pos = lower.find(query.lower())
    if pos == -1:
        return text[:radius * 2].strip() + ("..." if len(text) > radius * 2 else "")
    start = max(0, pos - radius)
    end = min(len(text), pos + len(query) + radius)
    snippet = text[start:end].strip()
    if start > 0:
        snippet = "..." + snippet
    if end < len(text):
        snippet = snippet + "..."
    return snippet


@bp.route("/help/search")
@login_required
def help_search():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify([])

    q_lower = query.lower()
    results = []
    for topic, entry in _get_index().items():
        title = entry["title"]
        text = entry["text"]
        title_hit = q_lower in title.lower()
        text_hit = q_lower in text.lower()
        if not (title_hit or text_hit):
            continue
        results.append({
            "topic": topic,
            "title": title,
            "snippet": _snippet(text, query),
            # title matches are more likely to be exactly what the
            # person is looking for, so surface those first
            "rank": 0 if title_hit else 1,
        })

    results.sort(key=lambda r: (r["rank"], r["title"]))
    for r in results:
        del r["rank"]

    return jsonify(results[:20])


@bp.route("/help/reload", methods=["POST"])
@login_required
def help_reload():
    # Small escape hatch for development: force the in-memory index
    # to be rebuilt from disk on the next search, e.g. right after
    # hand-editing a help file, without restarting the whole app.
    global _INDEX
    _INDEX = None
    return jsonify({"reloaded": True})
