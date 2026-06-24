"""
database
========================
MySQL-backed data layer using mysql-connector-python.
"""

from __future__ import annotations

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
                FOREIGN KEY (session_id) REFERENCES print_sessions(session_id)
            ) ENGINE=InnoDB;
        """)
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
    def _read_counters(self, cursor) -> tuple[int, int]:
        cursor.execute(
            "SELECT last_issued_serial, last_issued_random FROM serial_counter WHERE id = 1"
        )
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
    def reserve_range(self, qty: int) -> dict:
        from config import SERIAL_STEP, RANDOM_STEP

        conn = self.connect()
        cursor = conn.cursor(dictionary=True)

        last_serial, last_random = self._read_counters(cursor)

        serial_start = last_serial + SERIAL_STEP
        serial_end = serial_start + qty - 1

        random_start = last_random + RANDOM_STEP
        random_end = random_start + (qty - 1) * RANDOM_STEP

        cursor.execute(
            """INSERT INTO print_sessions
               (serial_range_start, serial_range_end,
                random_range_start, random_range_end,
                quantity_requested, status)
               VALUES (%s, %s, %s, %s, %s, 'issued')""",
            (serial_start, serial_end, random_start, random_end, qty),
        )
        session_id = cursor.lastrowid
        conn.commit()

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
        from config import RANDOM_STEP

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

        count = last_good_serial - row["serial_range_start"] + 1
        new_serial = last_good_serial
        new_random = row["random_range_start"] + (count - 1) * RANDOM_STEP

        cursor.execute(
            "UPDATE serial_counter SET last_issued_serial = %s, last_issued_random = %s "
            "WHERE id = 1",
            (new_serial, new_random),
        )

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
        conn = self.connect()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(
            """UPDATE print_sessions
               SET status = 'voided', confirmed_at = CURRENT_TIMESTAMP
               WHERE session_id = %s AND status = 'issued'""",
            (session_id,),
        )
        conn.commit()
        return cursor.rowcount > 0