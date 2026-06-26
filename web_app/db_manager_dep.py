import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "serial_exporter"))

from database import DatabaseManager
from config import MYSQL_CONFIG


def get_db_manager():
    db = DatabaseManager(MYSQL_CONFIG)
    db.init_db()
    try:
        yield db
    finally:
        db.close()
