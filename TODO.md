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
  - those counts come from importing the candidate SQL into a scratch
    database and querying it -- same step needed for schema
    validation anyway, just read the counts while it's there
  - maintenance mode (already built, see app/extensions.py) wraps the
    actual swap
  - upload step: uploaded file is the combined zip (database.sql +
    photos.zip) from cp_downloadsnapshot -- unzip that outer layer
    first to get back the two separate pieces before anything else
  - uploaded backups are one-shot, not added to backup_history/the
    table: validate (schema check) -> confirm -> restore -> delete
    the upload either way. No "save this upload into my history"
    option -- restoring from it again means re-uploading it
  - open question before building: does the configured DB user even
    have CREATE DATABASE privileges for the scratch-DB approach to
    work at all? Not yet verified.
