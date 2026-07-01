from web_app.database import DatabaseManager
from web_app.config import MYSQL_CONFIG


def get_db_manager():
    db = DatabaseManager(MYSQL_CONFIG)
    try:
        yield db
    finally:
        db.close()
