########################################################################
### OPTIONAL FIRST-RUN SAMPLE DATA
########################################################################
# Inserts a small set of sample locations, categories, boxes, and items
# (with bundled placeholder photos) so a fresh IMPS install isn't
# completely empty. This is opt-in -- called only from the first-run
# welcome page, only if the user checks "Install sample items" (see
# del_firstrun() in app/blueprints/main.py).
#
# Best-effort by design: this exists purely to make an empty install
# look nicer, not to enforce data integrity. A partial failure here
# (e.g. one sample image missing) shouldn't block someone from
# finishing setup, so individual pieces degrade gracefully rather than
# raising -- see _copy_sample_image()'s fallback to the "no photo"
# placeholder.

import os
import shutil
from datetime import date

from app.extensions import get_db_connection, ITEM_IMAGE_FS_DIR

# Bundled placeholder photos, tracked in the repo (unlike the live
# item-image directory, which is per-install/gitignored). Path is
# relative to the process's working directory, same convention as
# every other relative path in extensions.py/imps_config.toml.
SAMPLE_IMAGE_SOURCE_DIR = os.path.join("static", "images", "sample_data")

SAMPLE_LOCATIONS = ["Garage", "Attic"]
SAMPLE_CATEGORIES = ["Tools", "Books"]

# box_index below refers to a position in SAMPLE_BOXES, resolved to a
# real box_num at install time (see install_sample_data()).
SAMPLE_BOXES = [
    {"box_name": "Sample box - Garage shelf", "box_loc": "Garage"},
    {"box_name": "Sample box - Attic bin", "box_loc": "Attic"},
]

SAMPLE_ITEMS = [
    {
        "item_name": "Claw hammer",
        "item_cat": "Tools",
        "item_desc": "16 oz, wood handle",
        "image": "sample_hammer.jpg",
        "box_index": 0,
    },
    {
        "item_name": "Tape measure",
        "item_cat": "Tools",
        "item_desc": "25 ft, self-locking",
        "image": "sample_tape_measure.jpg",
        "box_index": 0,
    },
    {
        "item_name": "Field guide to birds",
        "item_cat": "Books",
        "item_desc": "Paperback, water-damaged cover",
        "image": "sample_book.jpg",
        "box_index": 1,
    },
    {
        "item_name": "Photo album",
        "item_cat": "Books",
        "item_desc": "Family photos, 1990s",
        "image": "sample_photo_album.jpg",
        "box_index": 1,
    },
]


def install_sample_data():
    """Insert the sample locations/categories/boxes/items described
    above. Safe to call against a database that already has real user
    data in it -- sample boxes are placed at the first available gap
    in box numbering (same approach as boxes.boxadd()) rather than
    assuming box 1/2 are free, and duplicate location/category names
    are silently skipped rather than erroring (both tables have a
    UNIQUE constraint on name -- see setup.sql)."""
    item_image_dir_abs = ITEM_IMAGE_FS_DIR

    with get_db_connection() as mydb:
        cursor = mydb.cursor()
        for loc_name in SAMPLE_LOCATIONS:
            try:
                cursor.execute("INSERT INTO locations (loc_name) VALUES (%s)", (loc_name,))
            except Exception:
                pass  # already exists -- fine, this is best-effort sample data
        cursor.close()

        cursor = mydb.cursor()
        for cat_name in SAMPLE_CATEGORIES:
            try:
                cursor.execute("INSERT INTO categories (cat_name) VALUES (%s)", (cat_name,))
            except Exception:
                pass
        cursor.close()

        ### FIND FREE BOX NUMBERS (same gap-finding approach as boxes.boxadd())
        cursor = mydb.cursor()
        cursor.execute("SELECT box_num FROM boxes ORDER BY box_num;")
        existing_box_nums = {row[0] for row in cursor.fetchall() if row[0] is not None}
        cursor.close()

        box_nums = []
        candidate = 1
        while len(box_nums) < len(SAMPLE_BOXES):
            if candidate not in existing_box_nums:
                box_nums.append(candidate)
                existing_box_nums.add(candidate)
            candidate += 1

        today = str(date.today())

        cursor = mydb.cursor()
        for box_num, box in zip(box_nums, SAMPLE_BOXES):
            cursor.execute(
                """INSERT INTO boxes (box_num, box_loc, box_name, box_date, box_last_changed)
                   VALUES (%s, %s, %s, %s, %s)""",
                (box_num, box["box_loc"], box["box_name"], today, today),
            )
        cursor.close()

        cursor = mydb.cursor()
        for item in SAMPLE_ITEMS:
            dest_filename = _copy_sample_image(item["image"], item_image_dir_abs)
            cursor.execute(
                """INSERT INTO items (item_name, box_num, item_pic, item_date, item_cat, item_desc)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (
                    item["item_name"],
                    box_nums[item["box_index"]],
                    dest_filename,
                    today,
                    item["item_cat"],
                    item["item_desc"],
                ),
            )
        cursor.close()


def _copy_sample_image(source_filename, item_image_dir_abs):
    """Copy one bundled sample image into the live item-image
    directory. Prefixed with 'sample_' (the bundled files already are)
    so these are easy to spot/bulk-delete later, and won't collide
    with a real upload's timestamp-suffixed filename. Falls back to
    the standard 'none.jpg' placeholder -- rather than raising -- if
    the source image is missing, so a packaging problem with the
    sample images doesn't block finishing setup."""
    source_path = os.path.join(SAMPLE_IMAGE_SOURCE_DIR, source_filename)
    if not os.path.isfile(source_path):
        return "none.jpg"

    dest_filename = source_filename  # already 'sample_'-prefixed
    dest_path = os.path.join(item_image_dir_abs, dest_filename)
    try:
        shutil.copyfile(source_path, dest_path)
    except OSError:
        return "none.jpg"
    return dest_filename
