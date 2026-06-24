"""
config
======================
Centralized configuration, constants, and DB connection settings.
"""

# ---------------------------------------------------------------------------
# CSV / export constants
# ---------------------------------------------------------------------------
SERIAL_COLUMN_HEADER = "SerialNumber"
RANDOM_COLUMN_HEADER = "RandomNumber"
EXPORT_FILENAME = "print_queue.csv"
QUANTITY_WARN_THRESHOLD = 10000

# ---------------------------------------------------------------------------
# Label / Zebra constants
# ---------------------------------------------------------------------------
ZEBRA_LABEL_FILE = "AutomatedZebraPrinter.lbl"

# Seed step sizes
SERIAL_STEP = 1
RANDOM_STEP = 15

# ---------------------------------------------------------------------------
# GUI theme constants
# ---------------------------------------------------------------------------
BG_COLOR = "#f0f0f0"
LARGE_FONT = ("Segoe UI", 12)
TITLE_FONT = ("Segoe UI", 14, "bold")
BTN_FONT = ("Segoe UI", 12, "bold")
RESULT_FONT = ("Segoe UI", 11)

# ---------------------------------------------------------------------------
# Database configurations
# ---------------------------------------------------------------------------
# Primary / company DB — update these values when moving to a shared server
COMPANY_MYSQL_CONFIG = {
    "host": "localhost",  # Replace with company DB host/IP
    "user": "root",  # Replace with company DB user
    "password": "",  # Replace with company DB password
    "database": "serial_tracker",
    "port": 3306,
}

# Fallback / local Laragon DB
LOCAL_MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "serial_tracker",
    "port": 3306,
}