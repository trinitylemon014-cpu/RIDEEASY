"""Unit tests for the Turso HTTP client (no network: requests is faked)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests

from app.repositories.turso_http import (
    DatabaseQueryError,
    DatabaseUnavailableError,
    TursoHTTPClient,
)


class FakeResponse:
    def __init__(self, payload=None, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Plays back a list of responses or exceptions, recording every call."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []
        self.closed = False

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


def execute_ok(cols, rows, affected=0):
    return FakeResponse({"results": [
        {"type": "ok", "response": {"type": "execute", "result": {
            "cols": [{"name": c} for c in cols], "rows": rows, "affected_row_count": affected,
        }}},
        {"type": "ok", "response": {"type": "close"}},
    ]})


def client_with(*script):
    session = FakeSession(*script)
    client = TursoHTTPClient("https://db.turso.io/", "tok", session=session)
    return client, session


class ExecuteTests(unittest.TestCase):
    def test_decodes_rows_and_sends_auth_timeout_and_typed_args(self):
        client, session = client_with(execute_ok(
            ["id", "score", "name", "gone"],
            [[{"type": "integer", "value": "7"}, {"type": "float", "value": 1.5},
              {"type": "text", "value": "Ann"}, {"type": "null"}]],
        ))
        rs = client.execute("SELECT * FROM t WHERE a = ? AND b = ?", (3, "x"))
        self.assertEqual(rs.columns, ["id", "score", "name", "gone"])
        self.assertEqual(rs.rows, [[7, 1.5, "Ann", None]])
        call = session.calls[0]
        self.assertEqual(call["url"], "https://db.turso.io/v2/pipeline")
        self.assertEqual(call["headers"]["Authorization"], "Bearer tok")
        self.assertEqual(call["timeout"], (3.05, 10.0))
        stmt = call["json"]["requests"][0]["stmt"]
        self.assertEqual(stmt["args"], [{"type": "integer", "value": "3"}, {"type": "text", "value": "x"}])

    def test_rows_affected(self):
        client, _ = client_with(execute_ok([], [], affected=4))
        self.assertEqual(client.execute("UPDATE t SET a = 1").rows_affected, 4)

    def test_sql_error_raises_query_error(self):
        client, _ = client_with(FakeResponse({"results": [
            {"type": "error", "error": {"message": "no such table: t"}}]}))
        with self.assertRaisesRegex(DatabaseQueryError, "no such table"):
            client.execute("SELECT * FROM t")


class TimeoutTests(unittest.TestCase):
    def test_read_timeout_is_retried_for_reads_then_raises_unavailable(self):
        client, session = client_with(
            requests.exceptions.ReadTimeout("slow"), requests.exceptions.ReadTimeout("slow"))
        with self.assertRaises(DatabaseUnavailableError):
            client.execute("SELECT 1")
        self.assertEqual(len(session.calls), 2)

    def test_read_timeout_recovers_on_retry(self):
        client, session = client_with(requests.exceptions.ReadTimeout("slow"), execute_ok(["x"], []))
        self.assertEqual(client.execute("SELECT 1").columns, ["x"])
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(session.closed)  # stale session was discarded before the retry

    def test_write_is_not_retried_after_read_timeout(self):
        client, session = client_with(requests.exceptions.ReadTimeout("slow"))
        with self.assertRaises(DatabaseUnavailableError):
            client.execute("INSERT INTO t VALUES (1)")
        self.assertEqual(len(session.calls), 1)

    def test_write_is_retried_after_connect_timeout(self):
        client, session = client_with(requests.exceptions.ConnectTimeout("no route"), execute_ok([], [], 1))
        self.assertEqual(client.execute("INSERT INTO t VALUES (1)").rows_affected, 1)

    def test_bad_credentials(self):
        client, _ = client_with(FakeResponse(status=401, text="Unauthorized"))
        with self.assertRaisesRegex(DatabaseUnavailableError, "credentials"):
            client.execute("SELECT 1")

    def test_server_error_on_read_is_retried(self):
        client, session = client_with(FakeResponse(status=503, text="busy"), execute_ok(["x"], []))
        client.execute("SELECT 1")
        self.assertEqual(len(session.calls), 2)


class BatchTests(unittest.TestCase):
    def _batch_response(self, step_results, step_errors):
        return FakeResponse({"results": [
            {"type": "ok", "response": {"type": "batch", "result": {
                "step_results": step_results, "step_errors": step_errors}}},
            {"type": "ok", "response": {"type": "close"}},
        ]})

    def test_atomic_batch_structure_and_results(self):
        ok = lambda n: {"cols": [], "rows": [], "affected_row_count": n}
        client, session = client_with(self._batch_response(
            [ok(0), ok(1), ok(2), ok(0), None], [None, None, None, None, None]))
        results = client.batch_atomic([("INSERT INTO a VALUES (?)", [1]), ("UPDATE b SET x = 1", [])])
        self.assertEqual([r.rows_affected for r in results], [1, 2])
        steps = session.calls[0]["json"]["requests"][0]["batch"]["steps"]
        self.assertEqual([s["stmt"]["sql"] for s in steps],
                         ["BEGIN", "INSERT INTO a VALUES (?)", "UPDATE b SET x = 1", "COMMIT", "ROLLBACK"])
        self.assertEqual(steps[3]["condition"], {"type": "ok", "step": 2})
        self.assertEqual(steps[4]["condition"], {"type": "not", "cond": {"type": "ok", "step": 3}})

    def test_failed_statement_raises_and_is_not_committed(self):
        ok = {"cols": [], "rows": [], "affected_row_count": 0}
        client, _ = client_with(self._batch_response(
            [ok, None, None, ok], [None, {"message": "UNIQUE constraint failed"}, None, None]))
        with self.assertRaisesRegex(DatabaseQueryError, "UNIQUE"):
            client.batch_atomic([("INSERT INTO a VALUES (1)", [])])

    def test_empty_batch_makes_no_request(self):
        client, session = client_with()
        self.assertEqual(client.batch_atomic([]), [])
        self.assertEqual(session.calls, [])


if __name__ == "__main__":
    unittest.main()
