"""
Minimal Turso / libSQL client over the HTTP "Hrana" pipeline API.

Replaces the deprecated ``libsql-client`` package. Differences that matter in production:

* Every request has hard connect and read timeouts, so a stalled network or database can
  never block a Gunicorn worker until it is killed (the ``WORKER TIMEOUT`` seen on login).
* There is no background thread or event loop: a call either returns, or raises
  ``DatabaseUnavailableError`` within a bounded time.
* Atomic multi-statement writes use an explicit BEGIN / COMMIT batch with ROLLBACK on error.

Only ``requests`` (already a dependency) is needed.
"""
import base64
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import requests

logger = logging.getLogger("rideeasy.turso")

DEFAULT_CONNECT_TIMEOUT = 3.05
DEFAULT_READ_TIMEOUT = 10.0

_READ_PREFIXES = ("SELECT", "PRAGMA", "WITH", "EXPLAIN")


class DatabaseUnavailableError(RuntimeError):
    """The remote database could not be reached in time, or the connection failed."""


class DatabaseQueryError(RuntimeError):
    """Turso reached the database but rejected a statement (SQL error, constraint, ...)."""


@dataclass
class ResultSet:
    columns: List[str] = field(default_factory=list)
    rows: List[List[Any]] = field(default_factory=list)
    rows_affected: int = 0
    last_insert_rowid: Optional[int] = None


def _encode_arg(value: Any) -> Dict[str, Any]:
    if value is None:
        return {"type": "null"}
    if isinstance(value, bool):
        return {"type": "integer", "value": str(int(value))}
    if isinstance(value, int):
        return {"type": "integer", "value": str(value)}
    if isinstance(value, float):
        return {"type": "float", "value": value}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(value)).decode("ascii")}
    return {"type": "text", "value": str(value)}


def _decode_value(cell: Dict[str, Any]) -> Any:
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        data = cell.get("base64", "")
        return base64.b64decode(data + "=" * (-len(data) % 4))
    return cell.get("value")


def _statement(sql: str, params: Sequence[Any] = ()) -> Dict[str, Any]:
    return {"sql": sql, "args": [_encode_arg(p) for p in params]}


def _to_result(raw: Dict[str, Any]) -> ResultSet:
    return ResultSet(
        columns=[c.get("name") for c in raw.get("cols", [])],
        rows=[[_decode_value(cell) for cell in row] for row in raw.get("rows", [])],
        rows_affected=int(raw.get("affected_row_count") or 0),
        last_insert_rowid=(
            int(raw["last_insert_rowid"]) if raw.get("last_insert_rowid") is not None else None
        ),
    )


def _is_read(sql: str) -> bool:
    return sql.lstrip().upper().startswith(_READ_PREFIXES)


class TursoHTTPClient:
    """Thread-safe synchronous client with bounded timeouts."""

    def __init__(
        self,
        url: str,
        auth_token: str = "",
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        session: Optional[requests.Session] = None,
    ):
        self.base_url = url.rstrip("/")
        self.auth_token = auth_token
        self.timeout = (connect_timeout, read_timeout)
        self._session = session or requests.Session()
        self._lock = threading.Lock()  # serialises connection-pool resets

    # -- transport ---------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _reset_session(self) -> None:
        """Close pooled keep-alive connections (they may be stale); the session stays usable."""
        with self._lock:
            try:
                self._session.close()
            except Exception:
                pass

    def _post(self, requests_payload: List[Dict[str, Any]], *, idempotent: bool) -> List[Dict[str, Any]]:
        body = {"requests": requests_payload + [{"type": "close"}]}
        url = f"{self.base_url}/v2/pipeline"
        attempts = 2
        last_error: Optional[Exception] = None

        for attempt in range(attempts):
            try:
                response = self._session.post(
                    url, json=body, headers=self._headers(), timeout=self.timeout
                )
            except requests.exceptions.ConnectTimeout as exc:
                # The request never reached the server, so retrying is always safe.
                last_error = exc
                self._reset_session()
                continue
            except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectionError) as exc:
                # The server may already have applied the statement: only retry reads.
                last_error = exc
                self._reset_session()
                if idempotent:
                    continue
                break
            except requests.exceptions.RequestException as exc:
                last_error = exc
                break

            if response.status_code == 401 or response.status_code == 403:
                raise DatabaseUnavailableError(
                    "Turso rejected the credentials (HTTP %d); check TURSO_AUTH_TOKEN." % response.status_code
                )
            if response.status_code >= 500 and idempotent and attempt + 1 < attempts:
                last_error = DatabaseUnavailableError(f"Turso returned HTTP {response.status_code}")
                continue
            if response.status_code != 200:
                detail = response.text[:300]
                if response.status_code >= 500:
                    raise DatabaseUnavailableError(f"Turso returned HTTP {response.status_code}: {detail}")
                raise DatabaseQueryError(f"Turso returned HTTP {response.status_code}: {detail}")

            try:
                payload = response.json()
            except ValueError as exc:
                raise DatabaseUnavailableError("Turso returned a non-JSON response.") from exc
            return payload.get("results", [])

        logger.error("Turso request failed: %s", last_error)
        raise DatabaseUnavailableError(
            f"Database did not respond in time ({type(last_error).__name__})."
        ) from last_error

    @staticmethod
    def _unwrap(item: Dict[str, Any]) -> Dict[str, Any]:
        if item.get("type") == "error":
            message = (item.get("error") or {}).get("message", "unknown database error")
            raise DatabaseQueryError(message)
        return item.get("response", {})

    # -- public API --------------------------------------------------------------

    def execute(self, sql: str, params: Sequence[Any] = ()) -> ResultSet:
        results = self._post(
            [{"type": "execute", "stmt": _statement(sql, params)}], idempotent=_is_read(sql)
        )
        response = self._unwrap(results[0])
        return _to_result(response.get("result", {}))

    def batch_atomic(self, statements: List[tuple]) -> List[ResultSet]:
        """
        Run (sql, params) pairs in one request as a single transaction.

        BEGIN, then each statement conditioned on the previous one succeeding, then COMMIT;
        if anything fails ROLLBACK runs and the failing statement's error is raised.
        Returns one ResultSet per input statement.
        """
        if not statements:
            return []

        steps: List[Dict[str, Any]] = [{"stmt": _statement("BEGIN")}]
        for index, (sql, params) in enumerate(statements):
            steps.append({
                "stmt": _statement(sql, params),
                "condition": {"type": "ok", "step": index},
            })
        commit_index = len(steps)
        steps.append({
            "stmt": _statement("COMMIT"),
            "condition": {"type": "ok", "step": commit_index - 1},
        })
        steps.append({
            "stmt": _statement("ROLLBACK"),
            "condition": {"type": "not", "cond": {"type": "ok", "step": commit_index}},
        })

        results = self._post(
            [{"type": "batch", "batch": {"steps": steps}}],
            idempotent=False,
        )
        response = self._unwrap(results[0]).get("result", {})
        step_results = response.get("step_results", [])
        step_errors = response.get("step_errors", [])

        for error in step_errors:
            if error:
                raise DatabaseQueryError(error.get("message", "transaction failed"))
        if commit_index >= len(step_results) or step_results[commit_index] is None:
            raise DatabaseQueryError("Transaction was not committed.")

        # step_results[0] is BEGIN; statements occupy 1..len(statements)
        return [_to_result(step_results[i + 1] or {}) for i in range(len(statements))]

    def close(self) -> None:
        try:
            self._session.close()
        except Exception:
            pass
