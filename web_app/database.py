"""
database
========================
MySQL-backed data layer using mysql-connector-python.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'serial_exporter'))

import mysql.connector
from mysql.connector import connection as cnx


class DatabaseManager:
    """Wraps MySQL connection; ensures atomic dual-counter reservation."""

    def __init__(self, config: dict) -> None:
        self._config = config
        self._conn: cnx.MySQLConnection | None = None

    # ------------------------------------------------------------------
    def connect(self) -> cnx.MySQLConnection:
        if self._conn is None:
            base_config = {k: v for k, v in self._config.items() if k != "database"}
            tmp_conn = mysql.connector.connect(**base_config)
            tmp_cursor = tmp_conn.cursor()
            tmp_cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{self._config['database']}`"
            )
            tmp_conn.commit()
            tmp_cursor.close()
            tmp_conn.close()

            self._conn = mysql.connector.connect(**self._config)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    def init_db(self) -> None:
        """Create tables if missing. Does NOT seed — that happens on first use."""
        from config import SERIAL_STEP, RANDOM_STEP

        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS serial_counter (
                id INT PRIMARY KEY CHECK (id = 1),
                last_issued_serial INT NOT NULL,
                last_issued_random INT NOT NULL
            ) ENGINE=InnoDB;
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS print_sessions (
                session_id INT PRIMARY KEY AUTO_INCREMENT,
                serial_range_start INT NOT NULL,
                serial_range_end INT NOT NULL,
                random_range_start INT NOT NULL,
                random_range_end INT NOT NULL,
                quantity_requested INT NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'issued',
                confirmed_good_through_serial INT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                confirmed_at TIMESTAMP
            ) ENGINE=InnoDB;
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_rows (
                row_id INT PRIMARY KEY AUTO_INCREMENT,
                session_id INT NOT NULL,
                serial_number INT NOT NULL,
                random_number INT NOT NULL,
                status ENUM('used', 'unused') NOT NULL DEFAULT 'unused',
                FOREIGN KEY (session_id) REFERENCES print_sessions(session_id)
            ) ENGINE=InnoDB;
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS print_queue (
                id INT PRIMARY KEY AUTO_INCREMENT,
                SerialNumber INT NOT NULL,
                RandomNumber INT NOT NULL
            ) ENGINE=InnoDB;
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id      INT PRIMARY KEY AUTO_INCREMENT,
                username     VARCHAR(64) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                role         ENUM('view_only', 'view_actions', 'admin') NOT NULL DEFAULT 'view_only',
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB;
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                user_id  INT NOT NULL,
                key_name VARCHAR(64) NOT NULL,
                value    TEXT NOT NULL,
                PRIMARY KEY (user_id, key_name),
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            ) ENGINE=InnoDB;
        """)
        # Migrate: convert old single-key app_settings to per-user schema
        try:
            cursor.execute("ALTER TABLE app_settings ADD COLUMN user_id INT NOT NULL DEFAULT 0")
            cursor.execute("ALTER TABLE app_settings DROP PRIMARY KEY")
            cursor.execute("ALTER TABLE app_settings ADD PRIMARY KEY (user_id, key_name)")
            conn.commit()
        except Exception:
            conn.rollback()
        # Migrate: add session_rows.status if missing
        try:
            cursor.execute("""
                ALTER TABLE session_rows
                ADD COLUMN status ENUM('used', 'unused') NOT NULL DEFAULT 'unused'
            """)
            conn.commit()
        except Exception:
            conn.rollback()
        # Migrate: add print_sessions.started_by_user_id if missing
        try:
            cursor.execute("""
                ALTER TABLE print_sessions
                ADD COLUMN started_by_user_id INT,
                ADD FOREIGN KEY (started_by_user_id) REFERENCES users(user_id) ON DELETE SET NULL
            """)
            conn.commit()
        except Exception:
            conn.rollback()
        # Backfill: assign NULL sessions to the admin user
        try:
            cursor.execute("""
                UPDATE print_sessions
                SET started_by_user_id = (
                    SELECT user_id FROM users WHERE username = 'admin' LIMIT 1
                )
                WHERE started_by_user_id IS NULL
            """)
            conn.commit()
        except Exception:
            conn.rollback()
        # Index: session_rows.serial_number (range exports, serial lookups)
        try:
            cursor.execute("CREATE INDEX idx_session_rows_serial ON session_rows (serial_number)")
            conn.commit()
        except Exception:
            conn.rollback()
        # Index: print_sessions.status (session list filtering)
        try:
            cursor.execute("CREATE INDEX idx_print_sessions_status ON print_sessions (status)")
            conn.commit()
        except Exception:
            conn.rollback()
        conn.commit()

    # ------------------------------------------------------------------
    def has_counter(self) -> bool:
        conn = self.connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT COUNT(*) AS cnt FROM serial_counter")
        row = cursor.fetchone()
        return row["cnt"] > 0

    # ------------------------------------------------------------------
    def seed_counters(self, starting_serial: int, starting_random: int) -> None:
        from config import SERIAL_STEP, RANDOM_STEP

        conn = self.connect()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT IGNORE INTO serial_counter (id, last_issued_serial, last_issued_random) "
            "VALUES (%s, %s, %s)",
            (1, starting_serial - SERIAL_STEP, starting_random - RANDOM_STEP),
        )
        conn.commit()

    # ------------------------------------------------------------------
    def _read_counters(self, cursor, lock: bool = False) -> tuple[int, int]:
        sql = "SELECT last_issued_serial, last_issued_random FROM serial_counter WHERE id = 1"
        if lock:
            sql += " FOR UPDATE"
        cursor.execute(sql)
        row = cursor.fetchone()
        if row is None:
            raise RuntimeError("serial_counter row missing — seed it first")
        return row["last_issued_serial"], row["last_issued_random"]

    # ------------------------------------------------------------------
    def get_next_serial(self) -> int:
        from config import SERIAL_STEP

        conn = self.connect()
        cursor = conn.cursor(dictionary=True)
        last_serial, _ = self._read_counters(cursor)
        return last_serial + SERIAL_STEP

    def get_next_random(self) -> int:
        from config import RANDOM_STEP

        conn = self.connect()
        cursor = conn.cursor(dictionary=True)
        _, last_random = self._read_counters(cursor)
        return last_random + RANDOM_STEP

    # ------------------------------------------------------------------
    def reserve_range(self, qty: int, user_id: int = None) -> dict:
        from config import SERIAL_STEP, RANDOM_STEP

        conn = self.connect()
        cursor = conn.cursor(dictionary=True)

        try:
            cursor.execute(
                "SELECT session_id, status FROM print_sessions "
                "ORDER BY session_id DESC LIMIT 1 FOR UPDATE"
            )
            last = cursor.fetchone()
            if last and last["status"] == "issued":
                raise RuntimeError("A print session is already in progress")

            last_serial, last_random = self._read_counters(cursor, lock=True)

            serial_start = last_serial + SERIAL_STEP
            serial_end = serial_start + qty - 1

            random_start = last_random + RANDOM_STEP
            random_end = random_start + (qty - 1) * RANDOM_STEP

            cursor.execute(
                """INSERT INTO print_sessions
                   (serial_range_start, serial_range_end,
                    random_range_start, random_range_end,
                    quantity_requested, status, started_by_user_id)
                   VALUES (%s, %s, %s, %s, %s, 'issued', %s)""",
                (serial_start, serial_end, random_start, random_end, qty, user_id),
            )
            session_id = cursor.lastrowid

            cursor.execute(
                "UPDATE serial_counter SET last_issued_serial = %s, last_issued_random = %s WHERE id = 1",
                (serial_end, random_end),
            )

            cursor.execute("DELETE FROM print_queue")
            cursor.executemany(
                "INSERT INTO print_queue (SerialNumber, RandomNumber) VALUES (%s, %s)",
                [(serial_start + i * SERIAL_STEP, random_start + i * RANDOM_STEP) for i in range(qty)],
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

        return {
            "session_id": session_id,
            "serial_range_start": serial_start,
            "serial_range_end": serial_end,
            "random_range_start": random_start,
            "random_range_end": random_end,
            "quantity_requested": qty,
        }

    # ------------------------------------------------------------------
    def confirm_session(self, session_id: int, last_good_serial: int) -> bool:
        from config import RANDOM_STEP, SERIAL_STEP

        conn = self.connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT serial_range_start, serial_range_end, random_range_start "
            "FROM print_sessions WHERE session_id = %s",
            (session_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return False

        if last_good_serial >= row["serial_range_end"]:
            status = "confirmed"
        else:
            status = "partial"

        cursor.execute(
            """UPDATE print_sessions
               SET status = %s, confirmed_good_through_serial = %s, confirmed_at = CURRENT_TIMESTAMP
               WHERE session_id = %s""",
            (status, last_good_serial, session_id),
        )

        if status == "partial":
            last_good_random = (
                row["random_range_start"]
                + (last_good_serial - row["serial_range_start"]) * RANDOM_STEP
            )
            cursor.execute(
                "UPDATE serial_counter SET last_issued_serial = %s, last_issued_random = %s WHERE id = 1",
                (last_good_serial, last_good_random),
            )

        count = last_good_serial - row["serial_range_start"] + 1

        for i in range(count):
            cursor.execute(
                "INSERT INTO session_rows (session_id, serial_number, random_number) "
                "VALUES (%s, %s, %s)",
                (
                    session_id,
                    row["serial_range_start"] + i,
                    row["random_range_start"] + i * RANDOM_STEP,
                ),
            )

        conn.commit()
        return True

    # ------------------------------------------------------------------
    def void_session(self, session_id: int) -> bool:
        from config import SERIAL_STEP, RANDOM_STEP

        conn = self.connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            "SELECT serial_range_start, random_range_start "
            "FROM print_sessions WHERE session_id = %s AND status = 'issued'",
            (session_id,),
        )
        row = cursor.fetchone()
        if not row:
            return False

        cursor.execute(
            """UPDATE print_sessions
               SET status = 'voided', confirmed_at = CURRENT_TIMESTAMP
               WHERE session_id = %s""",
            (session_id,),
        )
        cursor.execute(
            "UPDATE serial_counter SET last_issued_serial = %s, last_issued_random = %s WHERE id = 1",
            (row["serial_range_start"] - SERIAL_STEP, row["random_range_start"] - RANDOM_STEP),
        )
        conn.commit()
        return True
