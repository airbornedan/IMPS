# TODO

Running backlog of things worth doing later. Add with `/btw <note>`,
or edit this file directly. Move an item out (done, or no longer
relevant) when it's resolved -- git history covers the rest.

## Inbox
- restore from backups -- UI entry point is wired up (Restore button
  on cp_backups.html -> /cp_backuprestore, currently a placeholder page).
  Engine progress (app/blueprints/control_panel.py):
  - DONE: rewrite_dump_for_staging() -- rewrites a candidate .sql dump
    (categories/locations/boxes/items -> restore_staging_*, FK
    CONSTRAINT names too, backup_history dropped entirely). Verified
    against real backups from the demo box.
  - DONE: _swap_staging_tables_into_place() -- atomic RENAME TABLE
    promotes staging tables into place, drops the old ones, repairs FK
    constraint names back to canonical. Verified end-to-end on the
    live MariaDB test container: staged a real "items deleted" backup
    over a real full backup, exact item/box match, working FK joins,
    backup_history untouched, and a second restore back to the
    original with no leftover-state collision.
  - DONE: _restore_diff_counts() -- item/box counts, live vs. staged.
    Verified against the same real backup: 38/9 current, 26/9
    candidate, exact match.
  - NOT DONE: the confirm page itself (real page, not
    confirm_modal.html -- too much content for that component); logging
    at each step (see below); cleanup for abandoned staging tables (user
    opens the confirm page, never clicks Cancel or Restore -- nothing
    currently cleans those up); wiring cp_backuprestore up to actually
    call this engine; the upload path; maintenance mode (already built
    separately, see app/extensions.py) isn't yet wired around the real
    swap call; the safety-backup-before-swap step (reuse cp_backupnow's
    logic); the image-side restore (extract photos.zip over
    ITEM_IMAGE_FS_DIR, overlay not wipe-first)
  - logging: once the real route exists, log at each step (restore
    initiated + which snapshot/upload, staging counts, safety backup
    taken + its snapshot_id, entering maintenance mode, swap result,
    photo extraction result, exiting maintenance mode, and especially
    failure-recovery attempts + their outcome) -- matches this file's
    existing logger.error/warning/info conventions, not added to the
    bare tested functions themselves
  - upload step: uploaded file is the combined zip (database.sql +
    photos.zip) from cp_snapshotdownload -- unzip that outer layer
    first to get back the two separate pieces before anything else
  - uploaded backups are one-shot, not added to backup_history/the
    table: validate (schema check) -> confirm -> restore -> delete
    the upload either way. No "save this upload into my history"
    option -- restoring from it again means re-uploading it
- question about saved tabs
- restore_icon.png and upload_icon.png have inconsistent internal
  padding around their white glyph vs. the rest of the icon set --
  glyph fills ~67%/~42% of the canvas vs. download_icon.png's ~53%,
  so at the same button size restore looks bigger and upload looks
  smaller than the other icons, even though the red background square
  is the same size in all of them. Needs the PNGs redrawn with padding
  closer to the existing set, not a CSS fix. The original icons were
  drawn in a vector tool with a template meant to keep every glyph in
  sync -- track that tooling down (may be lost) before redrawing by
  eye.
- consolidate the migration scripts in deploy/tools/ before pushing
  this branch of work to the live Pi instance (currently:
  migrate_categories_schema.sh, migrate_backup_snapshot_column.sh,
  migrate_backup_drop_date_column.sh)
