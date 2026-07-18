import os
import sys

os.chdir("/var/www")
sys.path.insert(0, "/var/www")

from run import app as application
