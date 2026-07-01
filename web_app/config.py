import os
import glob as _glob

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

SESSION_SECRET_KEY = os.getenv("SESSION_SECRET_KEY", "change-me-in-production-32chars!")

DB_PATH = os.getenv("DB_PATH", "serial_numbers.db")

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
