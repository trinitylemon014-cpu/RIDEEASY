import os
import sqlite3
import logging
from typing import Any, Dict, List, Optional
from app.config import Config

logger = logging.getLogger("rideeasy.database")

class Database:
    """
    Unified Database abstraction layer supporting:
    1. Production: Turso libSQL client (via libsql_client sync driver)
    2. Local Development & Fallback: Local SQLite database file
    """
    _instance = None

    def __init__(self, db_url: Optional[str] = None, auth_token: Optional[str] = None):
        self.db_url = db_url or Config.TURSO_DATABASE_URL
        self.auth_token = auth_token or Config.TURSO_AUTH_TOKEN
        self.local_path = Config.LOCAL_DB_PATH
        self.is_turso = bool(self.db_url and (self.db_url.startswith("libsql://") or self.db_url.startswith("https://")))
        self._libsql_client = None

        if self.is_turso:
            try:
                import libsql_client
                logger.info(f"Connecting to remote Turso libSQL database: {self.db_url}")
                self._libsql_client = libsql_client.create_client_sync(
                    url=self.db_url,
                    auth_token=self.auth_token
                )
                logger.info("Successfully established connection to Turso database.")
            except Exception as e:
                logger.error(f"Failed to connect to Turso: {e}. Falling back to local SQLite at {self.local_path}")
                self.is_turso = False

    def _get_sqlite_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.local_path, timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def execute(self, query: str, params: tuple = ()) -> int:
        """Executes INSERT/UPDATE/DELETE query and returns rowcount or 1."""
        if self.is_turso and self._libsql_client:
            rs = self._libsql_client.execute(query, list(params))
            return rs.rows_affected if hasattr(rs, "rows_affected") else 1
        else:
            with self._get_sqlite_conn() as conn:
                cur = conn.execute(query, params)
                conn.commit()
                return cur.rowcount

    def fetchone(self, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Executes SELECT query and returns a single row as a dictionary."""
        if self.is_turso and self._libsql_client:
            rs = self._libsql_client.execute(query, list(params))
            if not rs.rows:
                return None
            columns = rs.columns
            row = rs.rows[0]
            return {columns[i]: row[i] for i in range(len(columns))}
        else:
            with self._get_sqlite_conn() as conn:
                cur = conn.execute(query, params)
                row = cur.fetchone()
                return dict(row) if row else None

    def fetchall(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Executes SELECT query and returns all matching rows as a list of dictionaries."""
        if self.is_turso and self._libsql_client:
            rs = self._libsql_client.execute(query, list(params))
            columns = rs.columns
            return [{columns[i]: r[i] for i in range(len(columns))} for r in rs.rows]
        else:
            with self._get_sqlite_conn() as conn:
                cur = conn.execute(query, params)
                rows = cur.fetchall()
                return [dict(r) for r in rows]

    def init_db(self, schema_file: Optional[str] = None):
        """Initializes tables using the schema SQL file."""
        if not schema_file:
            schema_file = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "database", "schema", "schema.sql"
            )

        if not os.path.exists(schema_file):
            logger.warning(f"Schema file not found at {schema_file}")
            return

        with open(schema_file, "r", encoding="utf-8") as f:
            sql_script = f.read()

        if self.is_turso and self._libsql_client:
            # Split and execute statements for Turso libSQL
            statements = [s.strip() for s in sql_script.split(";") if s.strip()]
            for stmt in statements:
                try:
                    self._libsql_client.execute(stmt)
                except Exception as e:
                    logger.warning(f"Error executing statement on Turso: {e}")
        else:
            with self._get_sqlite_conn() as conn:
                conn.executescript(sql_script)
                conn.commit()

        logger.info("Database schema initialized successfully.")

# Singleton accessor
_db_instance: Optional[Database] = None

def get_db() -> Database:
    global _db_instance
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
