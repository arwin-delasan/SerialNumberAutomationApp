from web_app.database import DatabaseManager
from web_app.config import DB_PATH


def get_db_manager():
    db = DatabaseManager(DB_PATH)
    try:
        yield db
    finally:
        db.close()
