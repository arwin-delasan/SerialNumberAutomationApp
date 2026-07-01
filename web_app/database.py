"""
database
========================
SQLite-backed data layer using the built-in sqlite3 module.
"""

from __future__ import annotations

import sqlite3


def _row_factory(cursor: sqlite3.Cursor, row: tuple) -> dict:
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


class DatabaseManager:
    """Wraps SQLite connection; ensures atomic dual-counter reservation."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, timeout=10, check_same_thread=False)
            self._conn.row_factory = _row_factory
            self._conn.isolation_level = None  # manual transaction control
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    def init_db(self) -> None:
        """Create tables if missing. Does NOT seed — that happens on first use."""
        conn = self.connect()
        conn.execute("BEGIN")
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS serial_counter (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    last_issued_serial INTEGER NOT NULL,
                    last_issued_random INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role          TEXT NOT NULL DEFAULT 'view_only',
                    created_at    TEXT DEFAULT (datetime('now', 'localtime'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS print_sessions (
                    session_id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                    serial_range_start            INTEGER NOT NULL,
                    serial_range_end              INTEGER NOT NULL,
                    random_range_start            INTEGER NOT NULL,
                    random_range_end              INTEGER NOT NULL,
                    quantity_requested            INTEGER NOT NULL,
                    status                        TEXT NOT NULL DEFAULT 'issued',
                    confirmed_good_through_serial INTEGER,
                    created_at                    TEXT DEFAULT (datetime('now', 'localtime')),
                    confirmed_at                  TEXT,
                    started_by_user_id            INTEGER,
                    mo_number                     TEXT,
                    FOREIGN KEY (started_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS session_rows (
                    row_id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id    INTEGER NOT NULL,
                    serial_number INTEGER NOT NULL,
                    random_number INTEGER NOT NULL,
                    status        TEXT NOT NULL DEFAULT 'unused',
                    FOREIGN KEY (session_id) REFERENCES print_sessions(session_id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS print_queue (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    SerialNumber INTEGER NOT NULL,
                    RandomNumber INTEGER NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
                    user_id  INTEGER NOT NULL,
                    key_name TEXT NOT NULL,
                    value    TEXT NOT NULL,
                    PRIMARY KEY (user_id, key_name),
                    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session_rows_serial ON session_rows (serial_number)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_print_sessions_status ON print_sessions (status)")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        # Seed default admin if no users exist
        cursor = conn.execute("SELECT COUNT(*) AS cnt FROM users")
        if cursor.fetchone()["cnt"] == 0:
            from web_app.auth import hash_password
            import os
            default_password = os.environ.get("DEFAULT_ADMIN_PASSWORD", "admin1234")
            conn.execute(
                "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'admin')",
                ("admin", hash_password(default_password)),
            )
            print(f"[init] Default admin created — username: admin  password: {default_password}")
            print("[init] Change this password immediately via /users after first login.")

    # ------------------------------------------------------------------
    def has_counter(self) -> bool:
        conn = self.connect()
        cursor = conn.execute("SELECT COUNT(*) AS cnt FROM serial_counter")
        row = cursor.fetchone()
        return row["cnt"] > 0

    # ------------------------------------------------------------------
    def seed_counters(self, starting_serial: int, starting_random: int) -> None:
        from web_app.config import SERIAL_STEP, RANDOM_STEP

        conn = self.connect()
        conn.execute(
            "INSERT OR IGNORE INTO serial_counter (id, last_issued_serial, last_issued_random) "
            "VALUES (?, ?, ?)",
            (1, starting_serial - SERIAL_STEP, starting_random - RANDOM_STEP),
        )

    # ------------------------------------------------------------------
    def _read_counters(self, conn: sqlite3.Connection) -> tuple[int, int]:
        cursor = conn.execute("SELECT last_issued_serial, last_issued_random FROM serial_counter WHERE id = 1")
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("serial_counter row missing — seed it first")
        return row["last_issued_serial"], row["last_issued_random"]

    # ------------------------------------------------------------------
    def get_next_serial(self) -> int:
        from web_app.config import SERIAL_STEP

        conn = self.connect()
        last_serial, _ = self._read_counters(conn)
        return last_serial + SERIAL_STEP

    def get_next_random(self) -> int:
        from web_app.config import RANDOM_STEP

        conn = self.connect()
        _, last_random = self._read_counters(conn)
        return last_random + RANDOM_STEP

    # ------------------------------------------------------------------
    def reserve_range(self, qty: int, user_id: int = None, mo_number: str = None) -> dict:
        from web_app.config import SERIAL_STEP, RANDOM_STEP

        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT session_id, status FROM print_sessions ORDER BY session_id DESC LIMIT 1"
            ).fetchone()
            if row and row["status"] == "issued":
                raise RuntimeError("A print session is already in progress")

            last_serial, last_random = self._read_counters(conn)

            serial_start = last_serial + SERIAL_STEP
            serial_end = serial_start + qty - 1

            random_start = last_random + RANDOM_STEP
            random_end = random_start + (qty - 1) * RANDOM_STEP

            cursor = conn.execute(
                """INSERT INTO print_sessions
                   (serial_range_start, serial_range_end,
                    random_range_start, random_range_end,
                    quantity_requested, status, started_by_user_id, mo_number)
                   VALUES (?, ?, ?, ?, ?, 'issued', ?, ?)""",
                (serial_start, serial_end, random_start, random_end, qty, user_id, mo_number),
            )
            session_id = cursor.lastrowid

            conn.execute(
                "UPDATE serial_counter SET last_issued_serial = ?, last_issued_random = ? WHERE id = 1",
                (serial_end, random_end),
            )

            conn.execute("DELETE FROM print_queue")
            conn.executemany(
                "INSERT INTO print_queue (SerialNumber, RandomNumber) VALUES (?, ?)",
                [(serial_start + i * SERIAL_STEP, random_start + i * RANDOM_STEP) for i in range(qty)],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        return {
            "session_id": session_id,
            "serial_range_start": serial_start,
            "serial_range_end": serial_end,
            "random_range_start": random_start,
            "random_range_end": random_end,
            "quantity_requested": qty,
            "mo_number": mo_number,
        }

    # ------------------------------------------------------------------
    def confirm_session(self, session_id: int, last_good_serial: int) -> bool:
        from web_app.config import RANDOM_STEP, SERIAL_STEP

        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT serial_range_start, serial_range_end, random_range_start "
                "FROM print_sessions WHERE session_id = ? AND status = 'issued'",
                (session_id,),
            ).fetchone()
            if row is None:
                conn.execute("ROLLBACK")
                return False

            if last_good_serial >= row["serial_range_end"]:
                status = "confirmed"
            else:
                status = "partial"

            conn.execute(
                """UPDATE print_sessions
                   SET status = ?, confirmed_good_through_serial = ?,
                       confirmed_at = datetime('now', 'localtime')
                   WHERE session_id = ?""",
                (status, last_good_serial, session_id),
            )

            if status == "partial":
                last_good_random = (
                    row["random_range_start"]
                    + (last_good_serial - row["serial_range_start"]) * RANDOM_STEP
                )
                conn.execute(
                    "UPDATE serial_counter SET last_issued_serial = ?, last_issued_random = ? WHERE id = 1",
                    (last_good_serial, last_good_random),
                )

            count = last_good_serial - row["serial_range_start"] + 1
            conn.executemany(
                "INSERT INTO session_rows (session_id, serial_number, random_number) VALUES (?, ?, ?)",
                [
                    (
                        session_id,
                        row["serial_range_start"] + i,
                        row["random_range_start"] + i * RANDOM_STEP,
                    )
                    for i in range(count)
                ],
            )

            conn.execute("DELETE FROM print_queue")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return True

    # ------------------------------------------------------------------
    def void_session(self, session_id: int) -> bool:
        from web_app.config import SERIAL_STEP, RANDOM_STEP

        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT serial_range_start, random_range_start "
                "FROM print_sessions WHERE session_id = ? AND status = 'issued'",
                (session_id,),
            ).fetchone()
            if not row:
                conn.execute("ROLLBACK")
                return False

            conn.execute(
                """UPDATE print_sessions
                   SET status = 'voided', confirmed_at = datetime('now', 'localtime')
                   WHERE session_id = ?""",
                (session_id,),
            )

            remaining = conn.execute(
                "SELECT COUNT(*) AS cnt FROM print_sessions WHERE status != 'voided'"
            ).fetchone()["cnt"]

            if remaining == 0:
                conn.execute("DELETE FROM serial_counter WHERE id = 1")
            else:
                conn.execute(
                    "UPDATE serial_counter SET last_issued_serial = ?, last_issued_random = ? WHERE id = 1",
                    (row["serial_range_start"] - SERIAL_STEP, row["random_range_start"] - RANDOM_STEP),
                )

            conn.execute("DELETE FROM print_queue")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return True
