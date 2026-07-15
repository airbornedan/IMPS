/*M!999999\- enable the sandbox mode */ 
-- MariaDB dump 10.19-11.8.6-MariaDB, for debian-linux-gnu (aarch64)
--
-- Host: localhost    Database: box_db2
-- ------------------------------------------------------
-- Server version	11.8.6-MariaDB-0+deb13u1 from Debian

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!40101 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*M!100616 SET @OLD_NOTE_VERBOSITY=@@NOTE_VERBOSITY, NOTE_VERBOSITY=0 */;

--
-- Table structure for table `boxes`
--

DROP TABLE IF EXISTS `boxes`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `boxes` (
  `box_num` int(11) DEFAULT NULL,
  `box_loc` varchar(30) DEFAULT NULL,
  `box_name` varchar(255) NOT NULL,
  `box_date` date NOT NULL,
  `box_last_changed` date NOT NULL,
  UNIQUE KEY `box_num_2` (`box_num`),
  KEY `box_num` (`box_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `boxes`
--

SET @OLD_AUTOCOMMIT=@@AUTOCOMMIT, @@AUTOCOMMIT=0;
LOCK TABLES `boxes` WRITE;
/*!40000 ALTER TABLE `boxes` DISABLE KEYS */;
INSERT INTO `boxes` VALUES
(1,'Storage room','','2025-08-05','2025-08-05'),
(2,'Storage room','','2025-08-05','2025-08-05'),
(3,'Storage room','','2025-08-17','2025-08-17'),
(4,'Storage room','','2025-08-18','2025-08-18'),
(5,'Storage room','','2025-08-20','2025-08-20'),
(6,'Storage room','','2025-08-22','2025-08-22'),
(7,'Storage room','','2025-08-22','2025-08-22'),
(8,'Storage room','','2026-06-25','2026-06-25'),
(9,'Storage room','','2026-06-27','2026-06-27');
/*!40000 ALTER TABLE `boxes` ENABLE KEYS */;
UNLOCK TABLES;
COMMIT;
SET AUTOCOMMIT=@OLD_AUTOCOMMIT;

--
-- Table structure for table `categories`
--

DROP TABLE IF EXISTS `categories`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `categories` (
  `cat_num` int(11) NOT NULL AUTO_INCREMENT,
  `cat_name` varchar(36) NOT NULL,
  PRIMARY KEY (`cat_num`)
) ENGINE=InnoDB AUTO_INCREMENT=217 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `categories`
--

SET @OLD_AUTOCOMMIT=@@AUTOCOMMIT, @@AUTOCOMMIT=0;
LOCK TABLES `categories` WRITE;
/*!40000 ALTER TABLE `categories` DISABLE KEYS */;
INSERT INTO `categories` VALUES
(1,'Uncategorized'),
(154,'Household'),
(155,'Wall decor'),
(156,'Decorating'),
(159,'Office'),
(160,'Kitchen'),
(170,'Tester'),
(174,'Decorating'),
(175,'Decorating'),
(176,'Decorating'),
(177,'Decorating'),
(178,'Decorating'),
(179,'Decorating'),
(180,'Decorating'),
(181,'Decorating'),
(182,'Decorating'),
(183,'Decorating'),
(184,'Decorating'),
(185,'Decorating'),
(186,'Decorating'),
(187,'Decorating'),
(188,'Decorating'),
(189,'Decorating'),
(190,'Decorating'),
(191,'Decorating'),
(192,'Decorating'),
(193,'Decorating'),
(194,'Decorating'),
(195,'Decorating'),
(196,'Decorating'),
(197,'Wall decor'),
(198,'Wall decor'),
(199,'Wall decor'),
(200,'Wall decor'),
(201,'Decorating'),
(202,'Decorating'),
(203,'Decorating'),
(204,'Decorating'),
(205,'Decorating'),
(206,'Decorating'),
(207,'Decorating'),
(208,'Decorating'),
(209,'Decorating'),
(210,'Decorating'),
(211,'Wall decor'),
(212,'Decorating'),
(213,'Kitchen'),
(214,'Decorating'),
(215,'Tester'),
(216,'Kitchen');
/*!40000 ALTER TABLE `categories` ENABLE KEYS */;
UNLOCK TABLES;
COMMIT;
SET AUTOCOMMIT=@OLD_AUTOCOMMIT;

--
-- Table structure for table `items`
--

DROP TABLE IF EXISTS `items`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `items` (
  `item_num` int(11) NOT NULL AUTO_INCREMENT,
  `item_name` varchar(256) NOT NULL,
  `box_num` int(11) DEFAULT NULL,
  `item_pic` varchar(255) DEFAULT 'none.jpg',
  `item_date` date NOT NULL,
  `item_cat` varchar(64) NOT NULL DEFAULT 'uncategorized',
  `item_desc` varchar(255) DEFAULT NULL,
  PRIMARY KEY (`item_num`),
  KEY `item_num` (`item_num`),
  FULLTEXT KEY `item_desc` (`item_desc`)
) ENGINE=InnoDB AUTO_INCREMENT=23542647 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `items`
--

SET @OLD_AUTOCOMMIT=@@AUTOCOMMIT, @@AUTOCOMMIT=0;
LOCK TABLES `items` WRITE;
/*!40000 ALTER TABLE `items` DISABLE KEYS */;
INSERT INTO `items` VALUES
(1,'Snail',1,'IMG_22601753393961.3702104.jpeg','2025-07-24','Decorating','Brown/Metal/Textured/Heavy'),
(2,'Owl',1,'IMG_22611753394194.336892.jpeg','2025-07-24','Decorating','Resin/Charcoal Gray/Tall/Smith & Hawken'),
(3,'8x10 Empty Clip Frame',2,'IMG_46681753395665.9701016.jpeg','2025-07-24','Wall decor','Landscape or Portrait Frame'),
(4,'8x10 Tree Sketch in Black Frame',2,'image1753395949.0935495.jpg','2025-07-24','Wall decor','Michelle Dujardin/Portrait Frame/Botanical Art'),
(5,'11x14 Set of Two Botanical Prints in Clip Frames',2,'IMG_46691753396298.3462243.jpeg','2025-07-24','Wall decor','Blue/Eucalyptus/Prints from Digital File/Landscape or Portrait Frame/Botanical Art'),
(6,'8x10 Set of Five Owl Prints in Wood Frames',2,'IMG_46701753397201.030576.jpeg','2025-07-24','Wall decor','With Mat/Hand Colored/West Elm/Wall or Tabletop/Landscape or Portrait Frame'),
(7,'8x10 Set of Five Tree Sketches in Clip Frames',2,'IMG_46711753398546.7061813.jpeg','2025-07-24','Wall decor','Michelle Dujardin/Live Oak/California Pepper/Eucalyptus/Landscape or Portrait Frame/Botanical Art'),
(8,'8x10 Set of Three Victorian Bathroom Prints in Clip Frames',2,'image1753399086.805977.jpg','2025-07-25','Wall decor','Landscape or Portrait Frame/Photographic Art'),
(9,'Lacquer Tray (white) with Handles',3,'image1753476102.1781511.jpg','2025-07-25','Decorating','White with Silver/Bird Silhouette/Botanical/Lacquer/Square'),
(10,'Large Decorative Bowl',3,'IMG_46721753477082.2774763.jpeg','2025-07-25','Decorating','Multicolor/Yellow/Teal/Green/Red/White/Floral/Botanical/Pier One/Coordinating Pitcher'),
(11,'4.5 Quart Mixing Bowl with Lid ',3,'image1753477795.458188.jpg','2025-07-25','Kitchen','Pyrex/Clear'),
(12,'Set of Two Fluted Serving Bowls',3,'image1753478006.6755762.jpg','2025-07-25','Kitchen','Pier One/Nesting/White'),
(13,'Large Glass Plate with Beaded Edge',3,'IMG_46741753478575.6694102.jpeg','2025-07-25','Kitchen','Clear'),
(14,'Large Decorative Glass Bowl',3,'IMG_46751753478716.8615396.jpeg','2025-07-25','Decorating','Clear/Spiral'),
(15,'Bread Basket with Warming Stone',3,'image1753479191.8827608.jpg','2025-07-25','Kitchen','Rectangular/Cotton Cloth Liner/\"Collin Bread Basket\" from Pier One'),
(16,'Decorative Lantern',4,'IMG_46761753741747.8221333.jpeg','2025-07-28','Decorating','Red/Six-sided/Metal/Candle Holder/Ring for Hanging'),
(17,'Glass Jar with Pom Pom Balls',4,'IMG_46771753742056.4643462.jpeg','2025-07-28','Decorating','Anchor Hocking/Brushed Metal Lid/1.5 Gallon/Red/White/Blue'),
(18,'Set of Four Glass Jars with Pom Pom Balls',5,'IMG_46781753825208.2252505.jpeg','2025-07-29','Decorating','Anchor Hocking/Brushed Metal Lids/64 Ounce/Red/White/Blue'),
(19,'Set of Three Faux Peony Arrangements in Glass Vases',6,'IMG_46791753912464.7088022.jpeg','2025-07-30','Decorating','Square Vases/Twelve Peonies/Floral/Botanical'),
(20,'Faux Magnolia Arrangement in Glass Vase',6,'IMG_46801753912704.477641.jpeg','2025-07-30','Decorating','Faux Water (discolored)/Floral/Botanical'),
(21,'Faux Rose Arrangement in Glass Vase',6,'image1753913098.310538.jpg','2025-07-30','Decorating','Green Glass/Faux Water/Floral/Botanical'),
(22,'5x7 Set of Three Black Frames',7,'IMG_46861754080330.744066.jpeg','2025-08-01','Wall decor','5x7 Matted Opening/Wood/Portrait Wall Frame'),
(23,'Embroidered Table Runner',7,'IMG_46881754080796.9677367.jpeg','2025-08-01','Decorating','Floral/Botanical/Green/Yellow/Teal/Coral/Pier One'),
(24,'A and Z Bookends',7,'IMG_46891754081074.1137912.jpeg','2025-08-01','Decorating','White/Wood'),
(25,'Venetian Glass Flower',7,'IMG_46901754081330.6008267.jpeg','2025-08-01','Decorating','Teal/Purchased in Venice by Evelyn/Floral/Botanical'),
(23542630,'6” Wood Letters',8,'image1782579408.5969634.jpg','2026-06-25','Wall decor','Antique White with Decorative Edge'),
(23542631,'Milk Bottle Vase',8,'image1782503188.1309478.jpg','2026-06-26','Decorating','Clear/Glass/Height: 11\"'),
(23542632,'7-Piece Glass Flower Vase with Metal Holder',8,'image1782579498.5367258.jpg','2026-06-26','Decorating','Length: 19\"/Bottle Height: 4\"'),
(23542633,'Pocket Watch Clock',8,'image1782504420.4123294.jpg','2026-06-26','Decorating','Pottery Barn/Pewter Finish/Roman Numerals/Desktop Display/Height: 8\"/Diameter: 5.5\"'),
(23542634,'Set of Two Decorative Book Boxes',8,'image1782579616.94886.jpg','2026-06-26','Decorating','Floral Folk Art Design with Animals/Yellow/Green'),
(23542635,'Small Pocket Watch Clock',8,'image1782508691.4932365.jpg','2026-06-26','Decorating','Bronze Finish/Desktop Display/Height: 4.5\"/Diameter: 3.75\"'),
(23542636,'Autumn Kiss Papercut',8,'image1782579986.3501115.jpg','2026-06-27','Wall decor','By Artist Tina Tarnoff/15.5\"x12.5\" Frame'),
(23542637,'8x10 Set of Four Wood Frames',9,'image1782596593.606406.jpg','2026-06-27','Wall decor','Landscape or Portrait Frame'),
(23542638,'Arc de Triomphe LEGO Architecture Set',9,'image1782596956.9751353.jpg','2026-06-27','Decorating','21036/Display Set'),
(23542639,'London LEGO Architecture Set',9,'image1782597511.431404.jpg','2026-06-27','Decorating','21034/Display Set'),
(23542640,'Sydney LEGO Architecture Set',9,'image1782610559.6158695.jpg','2026-06-28','Decorating','21032/Display Set'),
(23542641,'Paris LEGO Architecture Set',9,'image1782610778.6528494.jpg','2026-06-28','Decorating','21044/Display Set'),
(23542642,'Trafalgar Square LEGO Architecture Set',9,'image1782611065.0024445.jpg','2026-06-28','Decorating','21045/Display Set');
/*!40000 ALTER TABLE `items` ENABLE KEYS */;
UNLOCK TABLES;
COMMIT;
SET AUTOCOMMIT=@OLD_AUTOCOMMIT;

--
-- Table structure for table `locations`
--

DROP TABLE IF EXISTS `locations`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `locations` (
  `loc_name` varchar(255) NOT NULL,
  `loc_num` int(11) NOT NULL AUTO_INCREMENT,
  UNIQUE KEY `loc_num` (`loc_num`)
) ENGINE=InnoDB AUTO_INCREMENT=12 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `locations`
--

SET @OLD_AUTOCOMMIT=@@AUTOCOMMIT, @@AUTOCOMMIT=0;
LOCK TABLES `locations` WRITE;
/*!40000 ALTER TABLE `locations` DISABLE KEYS */;
INSERT INTO `locations` VALUES
('Unspecified',0),
('Storage room',1),
('Garage',2),
('Sun room',3),
('Basement',6),
('Attic',9);
/*!40000 ALTER TABLE `locations` ENABLE KEYS */;
UNLOCK TABLES;
COMMIT;
SET AUTOCOMMIT=@OLD_AUTOCOMMIT;

--
-- Table structure for table `settings`
--

DROP TABLE IF EXISTS `settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!40101 SET character_set_client = utf8mb4 */;
CREATE TABLE `settings` (
  `set_num` int(11) NOT NULL,
  `name` varchar(255) NOT NULL,
  `value` varchar(255) NOT NULL,
  UNIQUE KEY `set_num_2` (`set_num`),
  KEY `set_num` (`set_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `settings`
--

SET @OLD_AUTOCOMMIT=@@AUTOCOMMIT, @@AUTOCOMMIT=0;
LOCK TABLES `settings` WRITE;
/*!40000 ALTER TABLE `settings` DISABLE KEYS */;
INSERT INTO `settings` VALUES
(1,'backup_filename','static/backup//box_db2-1782663415.4121323.sql'),
(2,'last_backup','2026-06-28'),
(3,'archive_filename','static/backup/imps_imagearchive.2026-06-28.zip'),
(4,'last_archive','2026-06-28'),
(5,'saved_id','ar#wt324542!aw');
/*!40000 ALTER TABLE `settings` ENABLE KEYS */;
UNLOCK TABLES;
COMMIT;
SET AUTOCOMMIT=@OLD_AUTOCOMMIT;
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*M!100616 SET NOTE_VERBOSITY=@OLD_NOTE_VERBOSITY */;

-- Dump completed on 2026-06-29  0:47:38
