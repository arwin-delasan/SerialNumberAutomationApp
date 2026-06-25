"""
main
====================
Application entry point with company/local DB fallback logic.
"""

from __future__ import annotations

import sys

from config import MYSQL_CONFIG
from database import DatabaseManager
from gui import SerialExporterApp
import tkinter as tk


def main() -> None:
    db = DatabaseManager(MYSQL_CONFIG)
    db.init_db()

    root = tk.Tk()
    app = SerialExporterApp(root, db)
    try:
        root.mainloop()
    finally:
        db.close()


if __name__ == "__main__":
    main()