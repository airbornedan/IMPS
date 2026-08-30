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
IMPS is designed for use on your home network. It has only a single password and is not intended to be exposed to the public internet. To install IMPS, you will need a working python environment and a SQL-compatible database. Ideally, this would be a dedicated computer with a web server. IMPS was written and tested on Linux. It may work on macOS and Windows, but we hadn't tested it. We have a Raspberry Pi running Apache and mariadb to serve IMPS on our internal network. If none of that makes sense to you, we also have a Docker-based version available at getimps.com/downloads. The necessary instructions and files to create a Docker version are also included in the standard IMPS download.
### For Linux
If you are installing IMPS on your own Linux server, the steps are:

1. Update and upgrade

   ```
   sudo apt-get update
   sudo apt-get upgrade
   ```

2. Install and configure Apache.

   ```
   sudo apt-get install apache2
   ```

3. Install mysql or mariadb-server.

   ```
   sudo apt-get install mariadb-server
   ```

4. Install python3.

   ```
   sudo apt-get install python3
   ```

5. Install venv

   ```
   sudo apt-get install python3-venv
   ```

6. Install pip.

   ```
   sudo apt-get install python3-pip
   ```

7. Install unzip if not on your system

   ```
   apt install unzip
   ```

8. Move to the Apache root directory

   ```
   cd /var/www
   ```

9. Create a virtual environment.

   ```
   python3 -m venv .venv
   ```

10. Activate it.

    ```
    source .venv/bin/activate
    ```

11. If you do not have IMPS on your server, download it

    ```
    wget --no-check-certificate https://www.getimps.com/downloads/imps.zip
    ```

12. Unzip the IMPS files.

    ```
    unzip imps.zip
    ```

13. Install all required packages.

    ```
    pip install -r requirements.txt
    ```

14. Copy the example config file, then edit it to match your environment.

    ```
    cp imps_config.toml.example imps_config.toml
    ```

15. Set up the database

    ```
    cd deploy
    sudo ../.venv/bin/python3 db_setup.py
    ```

16. Test IMPS. Move back up to the IMPS root directory (step 15 left you in `deploy/`), then run IMPS using Python directly.

    ```
    cd ..
    python3 run.py
    ```

17. Browse to `<system ip address>:88`

18. Follow the on-screen directions to finish setting up IMPS.

19. Once you have IMPS configured and running, follow `deploy/apache/APACHE.md` to set it up under Apache/mod_wsgi (the recommended way to run IMPS long-term).

20. Start using the Inventory Management Photo System.
