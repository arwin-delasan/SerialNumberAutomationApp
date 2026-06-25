import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "serial_exporter"))

import mysql.connector
from config import MYSQL_CONFIG


def get_db():
    conn = mysql.connector.connect(**MYSQL_CONFIG)
    try:
        yield conn
    finally:
        conn.close()
