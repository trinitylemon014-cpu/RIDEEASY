import pytest

from app.config import Config
from app.repositories.database import Database, get_db
from database.migrations import seed_data


def test_database_pricing_seeded(db):
    pricing = db.fetchall("SELECT * FROM pricing_configs")
    categories = [p["category"] for p in pricing]
    assert "BODA" in categories
    assert "ECONOMY" in categories
    assert "COMFORT" in categories
    assert "PREMIUM" in categories
    assert "COASTER" in categories
    assert "BUS" in categories

def test_test_database_contains_only_test_fixtures_and_configured_admin(db):
    users = db.fetchall("SELECT email, role FROM users")
    emails = {u["email"]: u["role"] for u in users}
    assert "passenger@rideeasy.ug" in emails
    assert emails["passenger@rideeasy.ug"] == "PASSENGER"
    assert "driver@rideeasy.ug" in emails
    assert emails["driver@rideeasy.ug"] == "DRIVER"
    assert "school@rideeasy.ug" in emails
    assert emails["school@rideeasy.ug"] == "SCHOOL"
    assert "travel@rideeasy.ug" in emails
    assert emails["travel@rideeasy.ug"] == "TRAVEL_COMPANY"
    assert "admin@rideeasy.com" in emails
    assert emails["admin@rideeasy.com"] == "ADMIN"


def test_seed_repairs_missing_travel_fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "TURSO_DATABASE_URL", "")
    monkeypatch.setattr(Config, "LOCAL_DB_PATH", str(tmp_path / "seed.db"))
    db = Database()
    monkeypatch.setattr(seed_data, "get_db", lambda: db)

    monkeypatch.setattr(Config, "ADMIN_PASSWORD", "test-admin-password")
    seed_data.seed_database(include_demo_data=True)
    db.execute("DELETE FROM journey_reminders")
    db.execute("DELETE FROM confirmed_journeys")
    db.execute("DELETE FROM flight_bookings")
    db.execute("DELETE FROM flight_quotations")
    db.execute("DELETE FROM flight_requests")
    db.execute("DELETE FROM travel_companies")

    seed_data.seed_database(include_demo_data=True)

    assert db.fetchone("SELECT COUNT(*) AS count FROM travel_companies")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM flight_requests")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM flight_quotations")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM flight_bookings")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM confirmed_journeys")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM journey_reminders")["count"] == 5


def test_production_seed_removes_demo_accounts_and_creates_configured_admin(tmp_path):
    from app import create_app

    class TestSeedConfig(Config):
        SECRET_KEY = "test-only-rideeasy-secret"
        TESTING = True
        FLASK_ENV = "testing"
        TURSO_DATABASE_URL = ""
        TURSO_AUTH_TOKEN = ""
        LOCAL_DB_PATH = str(tmp_path / "production-seed.db")
        ADMIN_EMAIL = "admin@rideeasy.com"
        ADMIN_NAME = "katongole kylee"
        ADMIN_PASSWORD = "test-admin-password"
        ADMIN_PHONE = ""

    class ProductionSeedConfig(Config):
        SECRET_KEY = "test-only-rideeasy-secret"
        TESTING = False
        FLASK_ENV = "development"
        TURSO_DATABASE_URL = ""
        TURSO_AUTH_TOKEN = ""
        LOCAL_DB_PATH = str(tmp_path / "production-seed.db")
        ADMIN_EMAIL = "admin@rideeasy.com"
        ADMIN_NAME = "katongole kylee"
        ADMIN_PASSWORD = "test-production-admin-password"
        ADMIN_PHONE = ""

    create_app(TestSeedConfig)
    app = create_app(ProductionSeedConfig)
    with app.app_context():
        db = get_db()
        users = db.fetchall("SELECT email, role, full_name FROM users")
        assert users == [{
            "email": "admin@rideeasy.com",
            "role": "ADMIN",
            "full_name": "katongole kylee",
        }]
        assert db.fetchone("SELECT COUNT(*) AS count FROM rides")["count"] == 0
        assert db.fetchone("SELECT COUNT(*) AS count FROM pricing_configs")["count"] == 6


@pytest.mark.parametrize(
    ("database_url", "expected_message"),
    [
        ("", "TURSO_DATABASE_URL"),
        ("https://example.turso.io", "must use libsql://"),
    ],
)
def test_production_requires_transactional_turso_configuration(database_url, expected_message):
    from app import create_app

    class InvalidProductionConfig(Config):
        SECRET_KEY = "test-only-rideeasy-secret"
        TESTING = False
        FLASK_ENV = "production"
        TURSO_DATABASE_URL = database_url
        TURSO_AUTH_TOKEN = "test-token"
        ADMIN_PASSWORD = "test-production-admin-password"

    with pytest.raises(RuntimeError, match=expected_message):
        create_app(InvalidProductionConfig)
