# TODO

Running backlog of things worth doing later. Add with `/btw <note>`,
or edit this file directly. Move an item out (done, or no longer
relevant) when it's resolved -- git history covers the rest.

## Inbox
- restore from backups
  - upload step: uploaded file is the combined zip (database.sql +
    photos.zip) from cp_downloadsnapshot -- unzip that outer layer
    first to get back the two separate pieces before anything else
  - uploaded backups are one-shot, not added to backup_history/the
    table: validate (schema check) -> confirm -> restore -> delete
    the upload either way. No "save this upload into my history"
    option -- restoring from it again means re-uploading it
