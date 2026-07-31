-- IMPS table schema
--
-- Table creation only -- no CREATE USER/DATABASE/GRANT here, since
-- those require root and are handled separately in setup.sql. This
-- file is safe to run as box_user (given the grants in setup.sql),
-- which is what the in-app setup wizard (/setup) does automatically
-- once your database connection tests successfully.
--
-- Manual usage (if not using the wizard):
--   mysql -u box_user -p box_db < static/backup/schema.sql
--
-- MIGRATING AN EXISTING INSTALL: this file is for FRESH installs
-- only (it DROPs and recreates every table). Do not run this
-- against a database with existing data you want to keep.
--
-- Table order matters here: categories/locations are created first
-- because boxes/items now hold real foreign keys into them (see
-- below), instead of copying the category/location name into every
-- row as a plain string.

--
-- Table structure for table `categories`
--

DROP TABLE IF EXISTS `items`;
DROP TABLE IF EXISTS `boxes`;
DROP TABLE IF EXISTS `categories`;
CREATE TABLE `categories` (
  `cat_num` int NOT NULL AUTO_INCREMENT,
  `cat_name` varchar(64) NOT NULL,
  PRIMARY KEY (`cat_num`),
  UNIQUE KEY `uq_categories_cat_name` (`cat_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 'Uncategorized' is not a sample -- items.cat_num defaults to 0
-- (see app/blueprints/items.py), so this row must always exist at
-- cat_num 0, and the app refuses to let it be renamed or deleted
-- (see cp_editcat/cp_delcat in app/blueprints/control_panel.py).
INSERT INTO `categories` VALUES
(0,'Uncategorized');

--
-- Table structure for table `locations`
--

DROP TABLE IF EXISTS `locations`;
CREATE TABLE `locations` (
  `loc_name` varchar(255) NOT NULL,
  `loc_num` int NOT NULL AUTO_INCREMENT,
  PRIMARY KEY (`loc_num`),
  UNIQUE KEY `uq_locations_loc_name` (`loc_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 'Unspecified' is not a sample -- boxes.loc_num defaults to 0 when
-- no location is chosen (see app/blueprints/boxes.py), so this row
-- must always exist at loc_num 0, and the app refuses to let it be
-- renamed or deleted (see cp_editloc/cp_delloc in
-- app/blueprints/control_panel.py).
INSERT INTO `locations` VALUES
('Unspecified',0);

--
-- Table structure for table `boxes`
--

CREATE TABLE `boxes` (
  `box_num` int NOT NULL,
  `loc_num` int NOT NULL DEFAULT 0,
  `box_name` varchar(64) NOT NULL,
  `box_date` date NOT NULL,
  `box_last_changed` date NOT NULL,
  PRIMARY KEY (`box_num`),
  KEY `idx_boxes_loc_num` (`loc_num`),
  CONSTRAINT `fk_boxes_loc_num` FOREIGN KEY (`loc_num`) REFERENCES `locations` (`loc_num`)
    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- No sample box seeded here -- the welcome page's optional
-- "Install sample items" checkbox (see app/sample_data.py) adds a
-- richer set of sample boxes/items/categories/locations on demand
-- instead, so installs that skip the checkbox start genuinely empty.

--
-- Table structure for table `items`
--

CREATE TABLE `items` (
  `item_num` int NOT NULL AUTO_INCREMENT,
  `item_name` varchar(256) NOT NULL,
  `box_num` int DEFAULT NULL,
  `item_pic` varchar(255) DEFAULT 'none.jpg',
  `item_date` date NOT NULL,
  `cat_num` int NOT NULL DEFAULT 0,
  `item_desc` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`item_num`),
  KEY `idx_items_box_num` (`box_num`),
  KEY `idx_items_cat_num` (`cat_num`),
  FULLTEXT KEY `item_desc` (`item_desc`),
  CONSTRAINT `fk_items_cat_num` FOREIGN KEY (`cat_num`) REFERENCES `categories` (`cat_num`)
    ON DELETE RESTRICT ON UPDATE CASCADE,
  CONSTRAINT `fk_items_box_num` FOREIGN KEY (`box_num`) REFERENCES `boxes` (`box_num`)
    ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- No sample item seeded here -- see the boxes/categories sections
-- above for why (opt-in sample data now, via app/sample_data.py).
--
-- items.box_num IS a real foreign key: ON DELETE SET NULL means
-- deleting a box automatically orphans (rather than deletes) any
-- items still in it -- exactly the "I threw the box away but I'm not
-- ready to rehome what was in it yet" workflow the app's Cleanup ->
-- Orphaned Items tool already exists to surface (see
-- app/blueprints/boxes.py's boxorphanitemssuccess()). ON UPDATE
-- CASCADE means renumbering a box (boxrenumbersuccess()) automatically
-- carries every item in it along to the new number, with no separate
-- application-level cascade needed.

--
-- Table structure for table `backup_history`
--
-- Tracks the round-robin retention of DB/photo backups created from
-- the control panel (see _record_backup_and_prune() in
-- app/blueprints/control_panel.py).
--

DROP TABLE IF EXISTS `backup_history`;
CREATE TABLE `backup_history` (
  `id` int NOT NULL AUTO_INCREMENT,
  `backup_type` enum('db','image') NOT NULL,
  `filename` varchar(512) NOT NULL,
  `backup_date` date NOT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_type_created` (`backup_type`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- No seed rows for backup_history -- a fresh install has no backups yet.
