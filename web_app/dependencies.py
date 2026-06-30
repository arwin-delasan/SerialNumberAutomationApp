import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "serial_exporter"))

import mysql.connector.pooling
from config import MYSQL_CONFIG

_pool: mysql.connector.pooling.MySQLConnectionPool | None = None


def init_pool(pool_size: int = 5) -> None:
    global _pool
    _pool = mysql.connector.pooling.MySQLConnectionPool(
        pool_name="app_pool",
        pool_size=pool_size,
        **MYSQL_CONFIG,
    )


def get_db():
    conn = _pool.get_connection()
    try:
        yield conn
    finally:
        conn.close()
