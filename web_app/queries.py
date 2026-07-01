def get_counter_state(conn):
    with conn.cursor(dictionary=True) as cur:
        cur.execute("SELECT last_issued_serial, last_issued_random FROM serial_counter WHERE id = 1")
        return cur.fetchone()


def get_dashboard_stats(conn):
    with conn.cursor(dictionary=True) as cur:
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                SUM(status = 'confirmed') AS confirmed,
                SUM(status = 'partial')   AS partial,
                SUM(status = 'issued')    AS issued,
                SUM(status = 'voided')    AS voided
            FROM print_sessions
        """)
        return cur.fetchone()


def get_recent_sessions(conn, limit=10):
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT * FROM print_sessions ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
        return cur.fetchall()


def list_sessions(conn, page: int, page_size: int, search: str = None, status_filter: str = None, sort: str = "desc"):
    offset = (page - 1) * page_size
    order = "ASC" if sort == "asc" else "DESC"
    conditions = []
    params = []
    if search:
        conditions.append("(ps.mo_number LIKE %s OR u.username LIKE %s)")
        like = f"%{search}%"
        params.extend([like, like])
    if status_filter in ("issued", "confirmed", "partial", "voided"):
        conditions.append("ps.status = %s")
        params.append(status_filter)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with conn.cursor(dictionary=True) as cur:
        cur.execute(f"""
            SELECT ps.*, u.username AS started_by_username
            FROM print_sessions ps
            LEFT JOIN users u ON ps.started_by_user_id = u.user_id
            {where}
            ORDER BY ps.session_id {order}
            LIMIT %s OFFSET %s
        """, (*params, page_size, offset))
        rows = cur.fetchall()
        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM print_sessions ps
            LEFT JOIN users u ON ps.started_by_user_id = u.user_id
            {where}
        """, params)
        total = cur.fetchone()["total"]
    return rows, total


def get_active_session(conn):
    with conn.cursor(dictionary=True) as cur:
        cur.execute("SELECT * FROM print_sessions WHERE status = 'issued' ORDER BY session_id DESC LIMIT 1")
        return cur.fetchone()


def get_session(conn, session_id: int):
    with conn.cursor(dictionary=True) as cur:
        cur.execute("""
            SELECT ps.*, u.username AS started_by_username
            FROM print_sessions ps
            LEFT JOIN users u ON ps.started_by_user_id = u.user_id
            WHERE ps.session_id = %s
        """, (session_id,))
        return cur.fetchone()


def get_session_rows(conn, session_id: int):
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT row_id, serial_number, random_number FROM session_rows WHERE session_id = %s ORDER BY serial_number",
            (session_id,)
        )
        return cur.fetchall()


def get_session_rows_paged(conn, session_id: int, page: int, page_size: int):
    offset = (page - 1) * page_size
    with conn.cursor(dictionary=True) as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM session_rows WHERE session_id = %s", (session_id,))
        total = cur.fetchone()["cnt"]
        cur.execute(
            "SELECT row_id, serial_number, random_number FROM session_rows "
            "WHERE session_id = %s ORDER BY serial_number LIMIT %s OFFSET %s",
            (session_id, page_size, offset),
        )
        return cur.fetchall(), total


def get_serial_bounds(conn):
    with conn.cursor(dictionary=True) as cur:
        cur.execute("""
            SELECT MIN(sr.serial_number) AS min_serial,
                   MAX(sr.serial_number) AS max_serial
            FROM session_rows sr
            JOIN print_sessions ps ON sr.session_id = ps.session_id
            WHERE ps.status IN ('confirmed', 'partial')
        """)
        return cur.fetchone()


def update_serial_status(conn, row_id: int, status: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE session_rows SET status = %s WHERE row_id = %s",
            (status, row_id),
        )
    conn.commit()
    return cur.rowcount > 0


def bulk_update_serial_status(conn, ranges: list, serials: list, status: str) -> int:
    affected = 0
    with conn.cursor() as cur:
        for r in ranges:
            cur.execute(
                """UPDATE session_rows sr
                   JOIN print_sessions ps ON sr.session_id = ps.session_id
                   SET sr.status = %s
                   WHERE sr.serial_number BETWEEN %s AND %s
                     AND ps.status IN ('confirmed', 'partial')""",
                (status, r["start"], r["end"]),
            )
            affected += cur.rowcount
        if serials:
            placeholders = ",".join(["%s"] * len(serials))
            cur.execute(
                f"""UPDATE session_rows sr
                    JOIN print_sessions ps ON sr.session_id = ps.session_id
                    SET sr.status = %s
                    WHERE sr.serial_number IN ({placeholders})
                      AND ps.status IN ('confirmed', 'partial')""",
                [status, *serials],
            )
            affected += cur.rowcount
    conn.commit()
    return affected


def list_all_serials(conn, page: int, page_size: int, sort: str = "desc",
                     search: str = None, status_filter: str = None):
    if sort not in ("asc", "desc"):
        sort = "desc"
    offset = (page - 1) * page_size
    order = "DESC" if sort == "desc" else "ASC"

    conditions = ["ps.status IN ('confirmed', 'partial')"]
    params = []
    if search:
        conditions.append("(CAST(sr.serial_number AS CHAR) LIKE %s OR CAST(sr.random_number AS CHAR) LIKE %s)")
        like = f"%{search}%"
        params.extend([like, like])
    if status_filter in ("used", "unused"):
        conditions.append("sr.status = %s")
        params.append(status_filter)
    where = " AND ".join(conditions)

    with conn.cursor(dictionary=True) as cur:
        cur.execute(f"""
            SELECT sr.row_id, sr.serial_number, sr.random_number, sr.session_id, sr.status AS serial_status
            FROM session_rows sr
            JOIN print_sessions ps ON sr.session_id = ps.session_id
            WHERE {where}
            ORDER BY sr.serial_number {order}
            LIMIT %s OFFSET %s
        """, (*params, page_size, offset))
        rows = cur.fetchall()
        cur.execute(f"""
            SELECT COUNT(*) AS total
            FROM session_rows sr
            JOIN print_sessions ps ON sr.session_id = ps.session_id
            WHERE {where}
        """, params)
        total = cur.fetchone()["total"]
    return rows, total


def get_confirmed_rows_in_range(conn, start_serial: int, end_serial: int, status_filter: str = None):
    conditions = ["sr.serial_number BETWEEN %s AND %s", "ps.status IN ('confirmed', 'partial')"]
    params = [start_serial, end_serial]
    if status_filter in ("used", "unused"):
        conditions.append("sr.status = %s")
        params.append(status_filter)
    where = " AND ".join(conditions)
    with conn.cursor(dictionary=True) as cur:
        cur.execute(f"""
            SELECT DISTINCT sr.serial_number, sr.random_number
            FROM session_rows sr
            JOIN print_sessions ps ON sr.session_id = ps.session_id
            WHERE {where}
            ORDER BY sr.serial_number
        """, params)
        while True:
            batch = cur.fetchmany(500)
            if not batch:
                break
            yield from batch


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

def get_user_by_username(conn, username: str):
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT user_id, username, password_hash, role FROM users WHERE username = %s",
            (username,)
        )
        return cur.fetchone()


def get_user_by_id(conn, user_id: int):
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT user_id, username, role FROM users WHERE user_id = %s",
            (user_id,)
        )
        return cur.fetchone()


def list_users(conn):
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT user_id, username, role, created_at FROM users ORDER BY created_at"
        )
        return cur.fetchall()


def create_user(conn, username: str, password_hash: str, role: str):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (%s, %s, %s)",
            (username, password_hash, role)
        )
    conn.commit()


def update_user(conn, user_id: int, username: str, role: str, password_hash: str = None):
    with conn.cursor() as cur:
        if password_hash:
            cur.execute(
                "UPDATE users SET username=%s, role=%s, password_hash=%s WHERE user_id=%s",
                (username, role, password_hash, user_id)
            )
        else:
            cur.execute(
                "UPDATE users SET username=%s, role=%s WHERE user_id=%s",
                (username, role, user_id)
            )
    conn.commit()


def delete_user(conn, user_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM users WHERE user_id = %s", (user_id,))
    conn.commit()
    return cur.rowcount > 0


def count_admins(conn) -> int:
    with conn.cursor(dictionary=True) as cur:
        cur.execute("SELECT COUNT(*) AS cnt FROM users WHERE role = 'admin'")
        return cur.fetchone()["cnt"]


# ---------------------------------------------------------------------------
# App settings
# ---------------------------------------------------------------------------

def get_setting(conn, user_id: int, key: str):
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT value FROM app_settings WHERE user_id = %s AND key_name = %s",
            (user_id, key)
        )
        row = cur.fetchone()
        return row["value"] if row else None


def set_setting(conn, user_id: int, key: str, value: str):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO app_settings (user_id, key_name, value) VALUES (%s, %s, %s) "
            "ON DUPLICATE KEY UPDATE value = VALUES(value)",
            (user_id, key, value)
        )
    conn.commit()
