"""
main
====================
Application entry point with company/local DB fallback logic.
"""

from __future__ import annotations

import sys

from config import COMPANY_MYSQL_CONFIG, LOCAL_MYSQL_CONFIG
from database import DatabaseManager
from gui import SerialExporterApp
import tkinter as tk


def _try_connect(config: dict) -> DatabaseManager:
    db = DatabaseManager(config)
    db.init_db()
    return db


def main() -> None:
    db: DatabaseManager | None = None

    # Try company DB first, fall back to local
    try:
        db = _try_connect(COMPANY_MYSQL_CONFIG)
    except Exception as exc:
        print(f"Company DB unavailable, falling back to local DB: {exc}")
        try:
            db = _try_connect(LOCAL_MYSQL_CONFIG)
        except Exception as local_exc:
            print(f"Local DB also unavailable: {local_exc}")
            sys.exit("Cannot connect to any database.")

    root = tk.Tk()
    app = SerialExporterApp(root, db)
    try:
        root.mainloop()
    finally:
        db.close()


if __name__ == "__main__":
    main()