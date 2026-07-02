import os
import sys
import glob as _glob

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "change-me-in-production-32chars!")

_db_path = os.getenv("DB_PATH", "serial_numbers.db")
if not os.path.isabs(_db_path):
    # Anchor relative paths to the exe directory (frozen) or project root (dev)
    _anchor = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DB_PATH = os.path.join(_anchor, _db_path)
else:
    DB_PATH = _db_path

SERIAL_STEP = int(os.getenv("SERIAL_STEP", "1"))
RANDOM_STEP = int(os.getenv("RANDOM_STEP", "15"))

QUANTITY_WARN_THRESHOLD = 10000
SESSION_TIMEOUT_MINUTES = 90

SERIAL_COLUMN_HEADER = "SerialNumber"
RANDOM_COLUMN_HEADER = "RandomNumber"
EXPORT_FILENAME = "print_queue.csv"

LBL_PATH = os.getenv("LBL_PATH", "ZebraAutomated.lbl")
LBL_FILENAME = "ZebraAutomated.lbl"



def find_lbl_file() -> "str | None":
    search_roots = [
        os.path.dirname(os.path.abspath(__file__)),
        os.path.expanduser("~\\Desktop"),
        os.path.expanduser("~\\Documents"),
        os.path.expanduser("~"),
    ]
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for match in _glob.glob(os.path.join(root, "**", LBL_FILENAME), recursive=True):
            return match
    return None
