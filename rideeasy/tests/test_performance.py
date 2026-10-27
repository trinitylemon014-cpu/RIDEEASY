"""Speed-related behaviour: gzip, caching headers, and the one-query notification summary."""
import gzip
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from app.config import Config
from app.repositories.database import get_db


class PerfConfig(Config):
    SECRET_KEY = "test-only-rideeasy-secret"
    ADMIN_PASSWORD = "test-admin-password"
    TESTING = True
    FLASK_ENV = "testing"
    SESSION_COOKIE_SECURE = False
    LOCAL_DB_PATH = os.path.join(tempfile.mkdtemp(), "perf.db")
    TURSO_DATABASE_URL = ""
    TURSO_AUTH_TOKEN = ""
    DISPATCH_REQUIRE_DRIVER_LOCATION = False


class PerformanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(PerfConfig)

    def setUp(self):
        self.client = self.app.test_client()

    def test_html_is_gzipped_and_round_trips(self):
        plain = self.client.get("/", headers={"Accept-Encoding": "identity"})
        zipped = self.client.get("/", headers={"Accept-Encoding": "gzip, br"})
        self.assertNotIn("Content-Encoding", plain.headers)
        self.assertEqual(zipped.headers["Content-Encoding"], "gzip")
        self.assertIn("Accept-Encoding", zipped.headers["Vary"])
        self.assertEqual(gzip.decompress(zipped.data), plain.data)
        self.assertLess(len(zipped.data), len(plain.data) * 0.5)
        self.assertEqual(int(zipped.headers["Content-Length"]), len(zipped.data))

    def test_static_js_is_gzipped_once_and_cached_forever_when_versioned(self):
        raw = self.client.get("/static/js/app.js", headers={"Accept-Encoding": "identity"}).data
        for _ in range(2):  # second request is served from the in-memory cache
            r = self.client.get("/static/js/app.js?v=abc123", headers={"Accept-Encoding": "gzip"})
            self.assertEqual(r.headers["Content-Encoding"], "gzip")
            self.assertEqual(gzip.decompress(r.data), raw)
            self.assertIn("immutable", r.headers["Cache-Control"])
            self.assertIn("max-age=31536000", r.headers["Cache-Control"])

    def test_unversioned_css_revalidates_and_images_cache_30_days(self):
        css = self.client.get("/static/css/base.css")
        self.assertEqual(css.headers["Cache-Control"], "no-cache")
        img = self.client.get("/static/images/logo.png")
        self.assertEqual(img.headers["Cache-Control"], "public, max-age=2592000")
        self.assertNotIn("Content-Encoding", img.headers)  # PNGs are never re-compressed

    def test_conditional_request_still_returns_304(self):
        first = self.client.get("/static/css/base.css", headers={"Accept-Encoding": "identity"})
        etag = first.headers["ETag"]
        again = self.client.get("/static/css/base.css", headers={"If-None-Match": etag})
        self.assertEqual(again.status_code, 304)

    def test_logo_is_small(self):
        path = os.path.join(self.app.static_folder, "images", "logo.png")
        self.assertLess(os.path.getsize(path), 60_000)

    def test_pages_reference_versioned_assets(self):
        html = self.client.get("/auth/login").get_data(as_text=True)
        self.assertRegex(html, r'/static/css/base\.css\?v=\w+')
        self.assertRegex(html, r'/static/js/app\.js\?v=\w+')

    def test_unread_summary_uses_one_query_and_counts_beyond_the_limit(self):
        from app.services.notification_service import NotificationService
        with self.app.app_context():
            db = get_db()
            user = db.fetchone("SELECT id FROM users LIMIT 1")["id"]
            db.execute("DELETE FROM notifications WHERE user_id = ?", (user,))
            self.assertEqual(NotificationService.get_unread_summary(user, 5), (0, []))
            for i in range(7):
                db.execute(
                    "INSERT INTO notifications (id, user_id, title, message, type) VALUES (?, ?, ?, ?, ?)",
                    ("n%d" % i, user, "Title %d" % i, "Body", "SYSTEM"))
            calls = []
            original = db.fetchall
            db.fetchall = lambda q, p=(): (calls.append(q), original(q, p))[1]
            try:
                count, rows = NotificationService.get_unread_summary(user, 5)
            finally:
                db.fetchall = original
            self.assertEqual(count, 7)
            self.assertEqual(len(rows), 5)
            self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
