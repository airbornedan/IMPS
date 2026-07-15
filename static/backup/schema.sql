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
-- Table structure for table `boxes`
--

DROP TABLE IF EXISTS `boxes`;
CREATE TABLE `boxes` (
  `box_num` int NOT NULL,
  `box_loc` varchar(255) DEFAULT NULL,
  `box_name` varchar(255) NOT NULL,
  `box_date` date NOT NULL,
  `box_last_changed` date NOT NULL,
  PRIMARY KEY (`box_num`),
  KEY `idx_boxes_box_loc` (`box_loc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- No sample box seeded here -- the welcome page's optional
-- "Install sample items" checkbox (see app/sample_data.py) adds a
-- richer set of sample boxes/items/categories/locations on demand
-- instead, so installs that skip the checkbox start genuinely empty.

--
-- Table structure for table `categories`
--

DROP TABLE IF EXISTS `categories`;
CREATE TABLE `categories` (
  `cat_num` int NOT NULL AUTO_INCREMENT,
  `cat_name` varchar(36) NOT NULL,
  PRIMARY KEY (`cat_num`),
  UNIQUE KEY `uq_categories_cat_name` (`cat_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- 'Uncategorized' is not a sample -- items.item_cat defaults to it
-- (see app/blueprints/items.py), so it must always exist.
INSERT INTO `categories` VALUES
(0,'Uncategorized');

--
-- Table structure for table `items`
--

DROP TABLE IF EXISTS `items`;
CREATE TABLE `items` (
  `item_num` int NOT NULL AUTO_INCREMENT,
  `item_name` varchar(256) NOT NULL,
  `box_num` int DEFAULT NULL,
  `item_pic` varchar(255) DEFAULT 'none.jpg',
  `item_date` date NOT NULL,
  `item_cat` varchar(64) NOT NULL DEFAULT 'Uncategorized',
  `item_desc` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`item_num`),
  KEY `item_num` (`item_num`),
  KEY `idx_items_box_num` (`box_num`),
  KEY `idx_items_item_cat` (`item_cat`),
  FULLTEXT KEY `item_desc` (`item_desc`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;

-- No sample item seeded here -- see the boxes/categories sections
-- above for why (opt-in sample data now, via app/sample_data.py).

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

-- 'Unspecified' is not a sample -- boxes.box_loc defaults to it when
-- no location is chosen (see app/blueprints/boxes.py), so it must
-- always exist.
INSERT INTO `locations` VALUES
('Unspecified',0);

--
-- Table structure for table `backup_history`
--
-- Tracks the round-robin retention of DB/photo backups created from
-- the control panel (see _record_backup_and_prune() in
-- app/blueprints/control_panel.py). See deploy/tools/db_update.sql
-- for the migration that adds this table to an existing database
-- without touching anything else.
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
