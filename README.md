# IMPS 
IMPS is an open source tool for managing items in storage. My daughter and I wrote it as a fun exercise in coding together.  We wrote IMPS for our own personal use, but are sharing it here for others to use. You can use IMPS to keep an inventory of your stored items, organizing them into boxes, categories, and locations. Once items are in the database, IMPS will help you find and manage them.
### The Demo
There is a working demo of IMPS, set up with sample data, at demo.getimps.com.
## Concepts
To understand how IMPS works, you have to understand the underlying concepts.
### Items and Boxes
IMPS uses the idea of "items" for the things that you are storing, and the concept of "boxes" for the containers in which they are stored. Every item is required to have a name and be assigned to a box. Optionally, items can also have a category, photo, and description. Each item is also tagged with the date it was added to IMPS. Once items are in the database, you can search for them, view them based on their names, attributes, or category, or see a list of all your stored items.  Boxes have a number and can be given a name and assigned a location. In addition, you can see a list of boxes, or see items that are in a particular box. And of course there are tools for editing, moving, and deleting items and boxes too.
### QR Codes
IMPS makes viewing the contents of a box as easy as scanning a QR code. Once you have added a box to IMPS, you can print out a label that provides human-readable information (a box number and box name) as well as a QR code that links to the IMPS page for that box. Scan the QR code with your phone and IMPS will open the box inventory, showing you a list of all the items in the box, without you ever needing to take it down from the shelf and open it.
### **Views**
IMPs is designed to be used on desktop computers and mobile devices. To facilitate this, IMPS uses a responsive design that resizes the UI based on how large your browser screen is. In addition, on many IMPS pages, you will see a view switch at the top. The two available views are the simplified view and the detailed view. For items pages, simplified view is a tiled page of item images and the detailed view provides more comprehensive information. The current view is indicated in red. Clicking the non-highlighted view will switch views. If you are viewing the contents of a box in the detailed view, click the simplified icon and IMPS will show you the box contents in that view. IMPS will remember which view you were using last and show that view across the program. You can also set which columns IMPS displays in detailed mode from the control panel.
## Installation
IMPS is designed for use on your home network. It has only a single password and is not intended to be exposed to the public internet. To install IMPS, you will need a working python environment and a SQL-compatible database. Ideally, this would be a dedicated computer with a web server. IMPS was written and tested on Linux. It may work on macOS and Windows, but we hadn't tested it. We have a Raspberry Pi running Apache and mariadb to serve IMPS on our internal network. If none of that makes sense to you, we also have a Docker-based version available at getimps.com/downloads. 
### For Linux
If you are installing IMPS on your own Linux server, the steps are:
1. Install and configure Apache. 
       `sudo apt get install apache2`
2. Install mysql or mariadb-server.
       `sudo apt get install mariadb-server`
       At the end of this step, ensure you know the mariadb root password
3. Install python3.
       `sudo apt get install python3`
4. Install pip.
       `sudo apt get install python3-pip`
5. Create a virtual environment.
   `python3 -m venv .venv`
6. Activate it.
          `source .venv/bin/activate`
7. Place the IMPS files.
        `cd /var/www`
        `unzip imps.zip`
8. Install all required packages.
        `pip install -r requirements.txt`
9. Edit imps_config.toml to match your environment.
10. Run the sql setup
        `mysql -u root -p < deploy/schema.sql`
11. Test IMPS
      Stop Apache (it is currently running on Port 80)
        `service apache2 stop`
       Run IMPS using Python directly.
        `python3 run.py`
12. Follow the on-scree directions to finish setting up IMPS.
13. Once you have IMPS configured and running, use your friendly search engine to set up the app to run under wsgi.
       Some instructions (for the Apache specific case) are included in `deploy/apache/APACHE.md`
14. Start using the Inventory Management Photo System.