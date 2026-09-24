"""
core/repositories/base.py
========================
Base connection manager and caching helpers for database repositories.
"""
from __future__ import annotations
import sqlite3
from core.database import DB_PATH

def get_connection() -> sqlite3.Connection:
    """Return a newly opened SQLite connection configured with WAL mode."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        pass
    return conn
