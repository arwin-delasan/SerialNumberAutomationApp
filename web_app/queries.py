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


def list_sessions(conn, page: int, page_size: int):
    offset = (page - 1) * page_size
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT * FROM print_sessions ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (page_size, offset)
        )
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) AS total FROM print_sessions")
        total = cur.fetchone()["total"]
    return rows, total


def get_session(conn, session_id: int):
    with conn.cursor(dictionary=True) as cur:
        cur.execute("SELECT * FROM print_sessions WHERE session_id = %s", (session_id,))
        return cur.fetchone()


def get_session_rows(conn, session_id: int):
    with conn.cursor(dictionary=True) as cur:
        cur.execute(
            "SELECT row_id, serial_number, random_number FROM session_rows WHERE session_id = %s ORDER BY serial_number",
            (session_id,)
        )
        return cur.fetchall()


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


def list_all_serials(conn, page: int, page_size: int, sort: str = "desc"):
    offset = (page - 1) * page_size
    order = "DESC" if sort == "desc" else "ASC"
    with conn.cursor(dictionary=True) as cur:
        cur.execute(f"""
            SELECT DISTINCT sr.serial_number, sr.random_number, sr.session_id, sr.status AS serial_status
            FROM session_rows sr
            JOIN print_sessions ps ON sr.session_id = ps.session_id
            WHERE ps.status IN ('confirmed', 'partial')
            ORDER BY sr.serial_number {order}
            LIMIT %s OFFSET %s
        """, (page_size, offset))
        rows = cur.fetchall()
        cur.execute("""
            SELECT COUNT(DISTINCT sr.serial_number) AS total
            FROM session_rows sr
            JOIN print_sessions ps ON sr.session_id = ps.session_id
            WHERE ps.status IN ('confirmed', 'partial')
        """)
        total = cur.fetchone()["total"]
    return rows, total


def get_confirmed_rows_in_range(conn, start_serial: int, end_serial: int):
    with conn.cursor(dictionary=True) as cur:
        cur.execute("""
            SELECT DISTINCT sr.serial_number, sr.random_number
            FROM session_rows sr
            JOIN print_sessions ps ON sr.session_id = ps.session_id
            WHERE sr.serial_number BETWEEN %s AND %s
              AND ps.status IN ('confirmed', 'partial')
            ORDER BY sr.serial_number
        """, (start_serial, end_serial))
        while True:
            batch = cur.fetchmany(500)
            if not batch:
                break
            yield from batch
