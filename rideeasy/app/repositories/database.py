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
    2. Local Development: Local SQLite database file when no remote URL is configured
    """
    _instance = None

    def __init__(
        self,
        db_url: Optional[str] = None,
        auth_token: Optional[str] = None,
        local_path: Optional[str] = None
    ):
        self.db_url = Config.TURSO_DATABASE_URL if db_url is None else db_url
        self.auth_token = Config.TURSO_AUTH_TOKEN if auth_token is None else auth_token
        self.local_path = local_path or Config.LOCAL_DB_PATH
        self.is_turso = bool(
            self.db_url and self.db_url.startswith(("libsql://", "https://", "ws://", "wss://"))
        )
        self._libsql_client = None

        if self.is_turso:
            try:
                import libsql_client
                logger.info("Connecting to remote Turso libSQL database: %s", self.db_url)
                self._libsql_client = libsql_client.create_client_sync(
                    url=self.db_url,
                    auth_token=self.auth_token
                )
                logger.info("Successfully established connection to Turso database.")
            except Exception as e:
                logger.error("Failed to connect to configured Turso database: %s", e)
                raise RuntimeError("Configured Turso database is unavailable; refusing local fallback.") from e

    @property
    def supports_transactions(self) -> bool:
        return not self.is_turso or self.db_url.startswith(("libsql://", "ws://", "wss://"))

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

    def execute_transaction(self, operations: List[tuple]) -> List[int]:
        """Run a sequence of parameterized statements atomically."""
        if self.is_turso and self._libsql_client:
            transaction = self._libsql_client.transaction()
            try:
                rowcounts = []
                for operation in operations:
                    query, params = operation[:2]
                    result = transaction.execute(query, list(params))
                    rowcount = result.rows_affected if hasattr(result, "rows_affected") else 1
                    rowcounts.append(rowcount)
                    if len(operation) > 2 and operation[2] is not None and rowcount != operation[2]:
                        raise RuntimeError("Atomic database operation did not meet its row-count precondition.")
                transaction.commit()
                return rowcounts
            except Exception:
                transaction.rollback()
                raise

        with self._get_sqlite_conn() as conn:
            rowcounts = []
            for operation in operations:
                query, params = operation[:2]
                result = conn.execute(query, params)
                rowcounts.append(result.rowcount)
                if len(operation) > 2 and operation[2] is not None and result.rowcount != operation[2]:
                    raise RuntimeError("Atomic database operation did not meet its row-count precondition.")
            conn.commit()
            return rowcounts

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
            statements = [statement.strip() for statement in sql_script.split(";") if statement.strip()]
            for statement in statements:
                self._libsql_client.execute(statement)
        else:
            with self._get_sqlite_conn() as conn:
                conn.executescript(sql_script)
                conn.commit()

        for table, column, definition in (
            ("rewards_redemptions", "discount_percent", "INTEGER NOT NULL DEFAULT 0 CHECK(discount_percent BETWEEN 0 AND 100)"),
            ("rewards_redemptions", "ride_id", "TEXT"),
            ("rides", "driver_response_status", "TEXT NOT NULL DEFAULT 'ACCEPTED' CHECK(driver_response_status IN ('PENDING', 'ACCEPTED', 'DECLINED'))"),
            ("rides", "submission_key", "TEXT"),
            ("rides", "estimated_duration_minutes", "REAL")
        ):
            columns = self.fetchall(f"PRAGMA table_info({table})")
            if not any(item["name"] == column for item in columns):
                self.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

        self.execute(
            "CREATE INDEX IF NOT EXISTS idx_rides_dispatch_offer "
            "ON rides(driver_id, status, driver_response_status)"
        )
        self.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_rides_passenger_submission_key "
            "ON rides(passenger_id, submission_key)"
        )
        self.execute(
            """INSERT OR IGNORE INTO ride_driver_offers
               (ride_id, driver_id, status, expires_at)
               SELECT id, driver_id, 'PENDING', datetime(CURRENT_TIMESTAMP, ?)
               FROM rides
               WHERE driver_id IS NOT NULL AND status = 'DRIVER_ASSIGNED'
                 AND driver_response_status = 'PENDING'""",
            (f"+{min(300, max(1, Config.DRIVER_RIDE_OFFER_TIMEOUT_SECONDS))} seconds",)
        )
        logger.info("Database schema initialized successfully.")

# Singleton accessor
_db_instance: Optional[Database] = None

def get_db() -> Database:
    global _db_instance
    try:
        from flask import current_app, has_app_context
        if has_app_context():
            db_url = current_app.config.get("TURSO_DATABASE_URL", "")
            auth_token = current_app.config.get("TURSO_AUTH_TOKEN", "")
            local_path = current_app.config.get("LOCAL_DB_PATH", Config.LOCAL_DB_PATH)
            if (
                _db_instance is None
                or _db_instance.db_url != db_url
                or _db_instance.auth_token != auth_token
                or _db_instance.local_path != local_path
            ):
                _db_instance = Database(db_url, auth_token, local_path)
            return _db_instance
    except ImportError:
        pass
    if _db_instance is None:
        _db_instance = Database()
    return _db_instance
