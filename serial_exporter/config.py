"""
config
======================
Centralized configuration, constants, and DB connection settings.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ---------------------------------------------------------------------------
# CSV / export constants
# ---------------------------------------------------------------------------
SERIAL_COLUMN_HEADER = "SerialNumber"
RANDOM_COLUMN_HEADER = "RandomNumber"
EXPORT_FILENAME = "print_queue.csv"
QUANTITY_WARN_THRESHOLD = 10000

# Seed step sizes
SERIAL_STEP = 1
RANDOM_STEP = 15

# ---------------------------------------------------------------------------
# Modern GUI theme constants
# ---------------------------------------------------------------------------
BG_COLOR = "#f5f7fa"
CARD_BG = "#ffffff"
PRIMARY_COLOR = "#4a90e2"
PRIMARY_DARK = "#357abd"
PRIMARY_LIGHT = "#e3f2fd"
SUCCESS_COLOR = "#52c41a"
SUCCESS_BG = "#f6ffed"
SUCCESS_BORDER = "#b7eb8f"
TEXT_PRIMARY = "#262626"
TEXT_SECONDARY = "#595959"
TEXT_MUTED = "#8c8c8c"
BORDER_COLOR = "#e8e8e8"
SHADOW_COLOR = "#d9d9d9"
ERROR_COLOR = "#ff4d4f"
WARNING_COLOR = "#faad14"

LARGE_FONT = ("Segoe UI", 12)
TITLE_FONT = ("Segoe UI", 16, "bold")
BTN_FONT = ("Segoe UI", 11, "bold")
RESULT_FONT = ("Segoe UI", 10)
CARD_TITLE_FONT = ("Segoe UI", 11, "bold")
DISPLAY_FONT = ("Segoe UI", 24, "bold")

# ---------------------------------------------------------------------------
# Database configuration
# ---------------------------------------------------------------------------
# Reads from environment variables with fallback defaults
MYSQL_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "serial_tracker"),
    "port": int(os.getenv("DB_PORT", "3306")),
}
