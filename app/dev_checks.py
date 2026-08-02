########################################################################
### DEV-MODE STARTUP CHECKS
########################################################################
# Runs at startup when FLASK_DEBUG is set. Logs warnings only, never
# raises.
import inspect
import os
import re

from app.extensions import route_to_help_topic


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HELP_DIR = os.path.join(PROJECT_ROOT, "static", "help")
TEMPLATES_DIR = os.path.join(PROJECT_ROOT, "templates")
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")
BLUEPRINTS_DIR = os.path.join(PROJECT_ROOT, "app", "blueprints")


########################################################################
### CHECK 1: help file exists for every route that renders a page
########################################################################
def _topics_needing_help(app):
    """Help topics for every route whose view renders at least one
    non-errorpage.html template.

    Scans view source rather than calling views. Cannot see through
    helper functions.
    """
    topics = set()
    for rule in app.url_map.iter_rules():
        view = app.view_functions.get(rule.endpoint)
        if not view:
            continue
        try:
            src = inspect.getsource(view)
        except (OSError, TypeError):
            continue
        templates = re.findall(r'render_template\(\s*["\']([^"\']+)["\']', src)
        real_templates = [t for t in templates if t != "errorpage.html"]
        if real_templates:
            topics.add(route_to_help_topic(rule.rule))
    return topics


def check_help_coverage(app, logger):
    if not os.path.isdir(HELP_DIR):
        return

    expected_topics = _topics_needing_help(app)
    expected_files = {f"imps_{t}_help.html" for t in expected_topics}
    existing_files = {
        f for f in os.listdir(HELP_DIR)
        if f.startswith("imps_") and f.endswith("_help.html")
    }

    missing = sorted(expected_files - existing_files)
    extra = sorted(existing_files - expected_files)

    if missing:
        logger.warning(
            "[dev_checks] %d page(s) render content but have no matching "
            "help file: %s",
            len(missing), ", ".join(missing),
        )
    if extra:
        logger.warning(
            "[dev_checks] %d help file(s) match no current route: %s",
            len(extra), ", ".join(extra),
        )


########################################################################
### CHECK 2: every hardcoded template link points at a real route
########################################################################
_ATTR_RE = re.compile(r'(?:href|action)\s*=\s*"([^"]*)"')
_JINJA_EXPR_RE = re.compile(r"\{\{.*?\}\}")
_CONVERTER_RE = re.compile(r"<(?:[^:>]+:)?([^>]+)>")
_SCRIPT_BLOCK_RE = re.compile(r"<script\b.*?</script>", re.IGNORECASE | re.DOTALL)


def _shape(path):
    """Normalizes a URL path to a tuple of segments. Flask
    <converter> and Jinja {{ expression }} pieces collapse to '*'."""
    path = path.split("?")[0].split("#")[0]
    path = _JINJA_EXPR_RE.sub("*", path)
    path = _CONVERTER_RE.sub("*", path)
    return tuple(seg for seg in path.split("/") if seg != "")


def _is_known(shape, known_shapes):
    if shape in known_shapes:
        return True
    # A shorter shape that's a prefix of a real route (e.g.
    # action="/boxshowcontent/") counts as known -- a <script> block
    # completes it before use.
    return any(
        len(shape) < len(known) and known[: len(shape)] == shape
        for known in known_shapes
    )


def _known_route_shapes(app):
    return {_shape(rule.rule) for rule in app.url_map.iter_rules()}


def _template_links(templates_dir):
    for root, _dirs, files in os.walk(templates_dir):
        for fname in files:
            if not fname.endswith(".html"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8") as fh:
                    content = fh.read()
            except OSError:
                continue
            # href/action also match ordinary JS property assignments
            # (element.href = "..."); strip <script> blocks first.
            content = _SCRIPT_BLOCK_RE.sub("", content)
            for m in _ATTR_RE.finditer(content):
                yield fpath, m.group(1)


def check_template_links(app, logger):
    if not os.path.isdir(TEMPLATES_DIR):
        return

    known_shapes = _known_route_shapes(app)
    problems = []

    for fpath, link in _template_links(TEMPLATES_DIR):
        # External URLs, anchors, mailto:, javascript:, relative
        # links, and static assets are out of scope.
        if not link.startswith("/"):
            continue
        if link.startswith("/static/"):
            continue
        # A link that's entirely a Jinja expression has no literal
        # path to compare against a route shape.
        if _JINJA_EXPR_RE.sub("", link).strip("/") == "" and "{{" in link:
            continue

        if not _is_known(_shape(link), known_shapes):
            rel = os.path.relpath(fpath, TEMPLATES_DIR)
            problems.append(f"{rel}: {link}")

    if problems:
        logger.warning(
            "[dev_checks] %d template link(s) point at a route that "
            "doesn't exist: %s",
            len(problems), "; ".join(problems),
        )


########################################################################
### CHECK 3: every template file is reachable from a route
########################################################################
_RENDER_TEMPLATE_RE = re.compile(r'render_template\(\s*["\']([^"\']+)["\']')
_INCLUDE_EXTENDS_RE = re.compile(
    r'\{%-?\s*(?:include|extends|import)\s+["\']([^"\']+)["\']'
)


def _all_template_files():
    files = set()
    for root, _dirs, fnames in os.walk(TEMPLATES_DIR):
        for fname in fnames:
            if fname.endswith(".html"):
                rel = os.path.relpath(os.path.join(root, fname), TEMPLATES_DIR)
                files.add(rel.replace(os.sep, "/"))
    return files


def _templates_rendered_from_python():
    rendered = set()
    for root, _dirs, fnames in os.walk(os.path.join(PROJECT_ROOT, "app")):
        for fname in fnames:
            if not fname.endswith(".py"):
                continue
            try:
                with open(os.path.join(root, fname), encoding="utf-8") as fh:
                    src = fh.read()
            except OSError:
                continue
            rendered.update(_RENDER_TEMPLATE_RE.findall(src))
    return rendered


def check_orphaned_templates(app, logger):
    if not os.path.isdir(TEMPLATES_DIR):
        return

    all_files = _all_template_files()
    # Seed with templates named directly in a render_template() call,
    # then follow include/extends/import chains transitively. Only
    # catches literal string names.
    reachable = set()
    queue = [t for t in _templates_rendered_from_python() if t in all_files]
    reachable.update(queue)
    idx = 0
    while idx < len(queue):
        current = queue[idx]
        idx += 1
        fpath = os.path.join(TEMPLATES_DIR, current.replace("/", os.sep))
        try:
            with open(fpath, encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            continue
        for ref in _INCLUDE_EXTENDS_RE.findall(content):
            if ref in all_files and ref not in reachable:
                reachable.add(ref)
                queue.append(ref)

    orphans = sorted(all_files - reachable)
    if orphans:
        logger.warning(
            "[dev_checks] %d template file(s) are never rendered or "
            "included: %s",
            len(orphans), ", ".join(orphans),
        )


########################################################################
### CHECK 4: every route is @login_required or explicitly allowlisted
########################################################################
# Endpoints reachable without a login, with the reason each is open.
INTENTIONALLY_OPEN_ENDPOINTS = {
    "auth.login",  # reachable before a session exists
    "auth.attemptlogin",  # processes the login form
    "auth.logout",  # works even with an expired session
    "auth.loginfailed",  # shown after a failed attempt, pre-session
    "main.welcome",  # redirect only, no content
    "main.del_firstrun",  # gated on first.run's presence, not login
    "setup.setup_landing",
    "setup.setup_directories_info",
    "setup.setup_mariadb",
    "setup.setup_database",
    "setup.setup_samples",
    "setup.setup_password",  # entire /setup/* wizard: pre-password
    "static",  # Flask's built-in static-file endpoint
}


def check_login_required(app, logger):
    missing = []
    for rule in app.url_map.iter_rules():
        if rule.endpoint in INTENTIONALLY_OPEN_ENDPOINTS:
            continue
        view = app.view_functions.get(rule.endpoint)
        if not view:
            continue
        try:
            src = inspect.getsource(view)
        except (OSError, TypeError):
            continue
        if "@login_required" not in src:
            missing.append(rule.endpoint)

    missing = sorted(set(missing))
    if missing:
        logger.warning(
            "[dev_checks] %d route(s) aren't @login_required and aren't "
            "in dev_checks.INTENTIONALLY_OPEN_ENDPOINTS: %s",
            len(missing), ", ".join(missing),
        )


########################################################################
### CHECK 5: every static image asset is referenced somewhere
########################################################################
# Scoped to app UI assets. Excludes static/images/items/ (item
# photos, referenced by filename from the database) and
# static/images/sample_data/ and static/backup/ (generated files).
_ASSET_DIRS = [
    os.path.join(STATIC_DIR, "images"),
    os.path.join(STATIC_DIR, "help", "icons"),
]
_ASSET_EXCLUDE_DIRS = {
    os.path.join(STATIC_DIR, "images", "items"),
    os.path.join(STATIC_DIR, "images", "sample_data"),
}
_ASSET_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg")
_URL_REF_RE = re.compile(r'''["'(]([^"')]+\.(?:png|jpe?g|gif|ico|svg))["')]''')


def _all_asset_files():
    files = {}
    for base in _ASSET_DIRS:
        if not os.path.isdir(base):
            continue
        for root, dirs, fnames in os.walk(base):
            dirs[:] = [
                d for d in dirs if os.path.join(root, d) not in _ASSET_EXCLUDE_DIRS
            ]
            for fname in fnames:
                if fname.lower().endswith(_ASSET_EXTENSIONS):
                    files[fname] = os.path.join(root, fname)
    return files


def _text_files_to_scan():
    for base, exts in (
        (TEMPLATES_DIR, (".html",)),
        (STATIC_DIR, (".css", ".js")),
    ):
        for root, _dirs, fnames in os.walk(base):
            for fname in fnames:
                if fname.endswith(exts):
                    yield os.path.join(root, fname)


def check_unused_assets(app, logger):
    assets = _all_asset_files()
    if not assets:
        return

    referenced = set()
    for fpath in _text_files_to_scan():
        try:
            with open(fpath, encoding="utf-8") as fh:
                content = fh.read()
        except OSError:
            continue
        for m in _URL_REF_RE.finditer(content):
            referenced.add(os.path.basename(m.group(1)))

    unused = sorted(set(assets) - referenced)
    if unused:
        logger.warning(
            "[dev_checks] %d static image(s) under static/images/ or "
            "static/help/icons/ are unreferenced: %s",
            len(unused), ", ".join(unused),
        )


########################################################################
### CHECK 6: form fields a route reads are fields its own form sends
########################################################################
# Checks <form action="..."> blocks whose action resolves to exactly
# one known POST route. Flags fields the view reads via request.form
# that the form never sends. Does not flag the reverse (a field the
# form sends but the view doesn't read).
_FORM_BLOCK_RE = re.compile(
    r'<form\b[^>]*\baction\s*=\s*"([^"]*)"[^>]*>(.*?)</form>', re.IGNORECASE | re.DOTALL
)
_FIELD_NAME_RE = re.compile(
    r'<(?:input|select|textarea)\b[^>]*\bname\s*=\s*"([^"]+)"', re.IGNORECASE
)
_FORM_READ_RE = re.compile(r'request\.form(?:\.get)?\(?\[?\s*["\']([^"\']+)["\']')


def _route_view_for_shape(app, shape, method="POST"):
    matches = [
        rule for rule in app.url_map.iter_rules()
        if _shape(rule.rule) == shape and method in rule.methods
    ]
    if len(matches) != 1:
        return None
    return app.view_functions.get(matches[0].endpoint)


def check_form_field_names(app, logger):
    if not os.path.isdir(TEMPLATES_DIR):
        return

    problems = []
    for root, _dirs, fnames in os.walk(TEMPLATES_DIR):
        for fname in fnames:
            if not fname.endswith(".html"):
                continue
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, encoding="utf-8") as fh:
                    content = fh.read()
            except OSError:
                continue
            content = _SCRIPT_BLOCK_RE.sub("", content)

            for action, body in _FORM_BLOCK_RE.findall(content):
                if not action.startswith("/"):
                    continue
                view = _route_view_for_shape(app, _shape(action))
                if not view:
                    continue
                try:
                    view_src = inspect.getsource(view)
                except (OSError, TypeError):
                    continue

                sent = set(_FIELD_NAME_RE.findall(body))
                read = set(_FORM_READ_RE.findall(view_src))
                # csrf_token is handled by Flask-WTF, not read via
                # request.form in view code.
                unsent = read - sent - {"csrf_token"}
                if unsent:
                    rel = os.path.relpath(fpath, TEMPLATES_DIR)
                    problems.append(
                        f"{rel} -> {action}: view reads {sorted(unsent)} "
                        f"but the form never sends them"
                    )

    if problems:
        logger.warning(
            "[dev_checks] %d form/route field-name mismatch(es): %s",
            len(problems), "; ".join(problems),
        )


########################################################################
### JINJA DebugUndefined
########################################################################
# Renders a missing template variable as a visible {{ variable }}
# placeholder instead of an empty string.
def enable_debug_undefined(app):
    from jinja2 import DebugUndefined

    app.jinja_env.undefined = DebugUndefined


########################################################################
### ENTRY POINT
########################################################################
def run_dev_checks(app):
    # Advisory only. A failure here must not block startup.
    try:
        enable_debug_undefined(app)
        check_help_coverage(app, app.logger)
        check_template_links(app, app.logger)
        check_orphaned_templates(app, app.logger)
        check_login_required(app, app.logger)
        check_unused_assets(app, app.logger)
        check_form_field_names(app, app.logger)
    except Exception:
        app.logger.exception("[dev_checks] startup check failed to run")
