-- IMPS database setup
--
-- Creates the box_db database and a box_user account scoped to it.
-- Run this part as root/admin -- IMPS itself never has (and shouldn't
-- have) credentials that can create other MySQL users or databases.
--
-- Edit the username/password below before running this against a
-- real install, then use the SAME values when the in-app setup
-- wizard (/setup) asks for your database credentials -- it uses this
-- account to create the actual tables (see schema.sql), an operation
-- box_user's own grants below are sufficient for.
--
-- Usage:
--   sudo mysql -u root < deploy/setup.sql

CREATE USER IF NOT EXISTS 'box_user'@'localhost' IDENTIFIED BY 'box_pass';

CREATE DATABASE IF NOT EXISTS `box_db` DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci;
USE `box_db`;

-- CREATE/DROP/ALTER/INDEX/REFERENCES added (beyond the original
-- SELECT/INSERT/UPDATE/DELETE/LOCK TABLES) so box_user can run
-- schema.sql itself -- either via the setup wizard or by hand --
-- without needing a root connection for that step too. REFERENCES is
-- required specifically because schema.sql's boxes/items tables
-- declare foreign keys against categories/locations; without it,
-- table creation fails with "REFERENCES command denied" the moment it
-- hits the first FOREIGN KEY constraint. Scoped to box_db.* only, so
-- this doesn't grant anything outside this one database.
GRANT SELECT, INSERT, UPDATE, DELETE, LOCK TABLES, CREATE, DROP, ALTER, INDEX, REFERENCES
    ON box_db.* TO 'box_user'@'localhost';
FLUSH PRIVILEGES;

-- Table creation lives in schema.sql (kept separate so the setup
-- wizard -- which connects as box_user, not root -- can execute just
-- the table DDL without re-running the CREATE USER/DATABASE/GRANT
-- statements above, which require root). If you're doing everything
-- by hand instead of via the wizard, run schema.sql right after this
-- file:
--
--   sudo mysql -u root < deploy/setup.sql
--   mysql -u box_user -p box_db < deploy/schema.sql


