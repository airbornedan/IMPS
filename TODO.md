# TODO

Running backlog of things worth doing later. Add with `/btw <note>`,
or edit this file directly. Move an item out (done, or no longer
relevant) when it's resolved -- git history covers the rest.

## Inbox
- restore from backups -- UI entry point is wired up (Restore button
  on cp_backups.html -> /cp_restore, currently a placeholder page).
  The actual engine is not built. Design decisions already made:
  - clicking Restore always leads to a real confirm PAGE (not the
    confirm_modal.html component -- too much content for it), showing
    a before/after comparison (current item/box counts vs. the
    backup's), not just a bare "are you sure"
  - NOT a scratch database -- box_user's grant (deploy/db_setup.py) is
    deliberately scoped to box_db.* only, no CREATE DATABASE. Instead:
    stage inside box_db itself, using prefixed tables (e.g.
    restore_staging_items, restore_staging_boxes) built from the
    candidate SQL with its CREATE TABLE/INSERT INTO statements
    rewritten to those names. Validate + compute before/after counts
    against the staging tables, then swap into place with one atomic
    RENAME TABLE once confirmed. No privilege change, no root password
    prompt anywhere in the running app.
  - maintenance mode (already built, see app/extensions.py) wraps the
    actual swap
  - upload step: uploaded file is the combined zip (database.sql +
    photos.zip) from cp_downloadsnapshot -- unzip that outer layer
    first to get back the two separate pieces before anything else
  - uploaded backups are one-shot, not added to backup_history/the
    table: validate (schema check) -> confirm -> restore -> delete
    the upload either way. No "save this upload into my history"
    option -- restoring from it again means re-uploading it
- question about saved tabs
