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
        ("http://example.turso.io", "must use libsql://"),
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


def _counting_db(tmp_path, monkeypatch, name):
    """Local database whose query count and init_db calls can be inspected."""
    monkeypatch.setattr(Config, "TURSO_DATABASE_URL", "")
    monkeypatch.setattr(Config, "LOCAL_DB_PATH", str(tmp_path / name))
    monkeypatch.setattr(Config, "ADMIN_PASSWORD", "test-admin-password")
    db = Database()
    monkeypatch.setattr(seed_data, "get_db", lambda: db)
    state = {"queries": 0, "init_calls": 0}
    for method_name in ("execute", "fetchone", "fetchall", "execute_transaction"):
        original = getattr(db, method_name)

        def wrapper(*args, _original=original, **kwargs):
            state["queries"] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(db, method_name, wrapper)
    original_init = db.init_db

    def counting_init(*args, **kwargs):
        state["init_calls"] += 1
        return original_init(*args, **kwargs)

    monkeypatch.setattr(db, "init_db", counting_init)
    return db, state


def test_restart_skips_schema_setup_and_uses_few_queries(tmp_path, monkeypatch):
    db, state = _counting_db(tmp_path, monkeypatch, "restart.db")

    seed_data.seed_database(include_demo_data=False)
    assert state["init_calls"] == 1
    assert db.fetchone("SELECT value FROM app_meta WHERE key = 'schema_fingerprint'") is not None
    admin_count = db.fetchone("SELECT COUNT(*) AS count FROM users WHERE role = 'ADMIN'")["count"]
    assert admin_count == 1

    state["queries"] = 0
    seed_data.seed_database(include_demo_data=False)  # simulates a restart / wake-up

    assert state["init_calls"] == 1, "schema setup must not run again when nothing changed"
    assert state["queries"] <= 6, f"restart used {state['queries']} queries"
    assert db.fetchone("SELECT COUNT(*) AS count FROM users WHERE role = 'ADMIN'")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM pricing_configs")["count"] == 6


def test_changed_schema_fingerprint_reruns_setup_once(tmp_path, monkeypatch):
    db, state = _counting_db(tmp_path, monkeypatch, "fingerprint.db")
    seed_data.seed_database(include_demo_data=False)
    assert state["init_calls"] == 1

    monkeypatch.setattr(seed_data, "_schema_fingerprint", lambda: "new-version")
    seed_data.seed_database(include_demo_data=False)
    assert state["init_calls"] == 2
    seed_data.seed_database(include_demo_data=False)
    assert state["init_calls"] == 2


def test_existing_database_without_marker_is_upgraded(tmp_path, monkeypatch):
    """A database created by an older release has no app_meta table; setup must run once."""
    db, state = _counting_db(tmp_path, monkeypatch, "legacy.db")
    seed_data.seed_database(include_demo_data=False)
    db.execute("DROP TABLE app_meta")
    state["init_calls"] = 0

    seed_data.seed_database(include_demo_data=False)
    assert state["init_calls"] == 1
    assert db.schema_is_current(seed_data._schema_fingerprint())


def test_upgrade_creates_live_tracking_and_safety_tables_and_columns(tmp_path, monkeypatch):
    """A database from before live tracking gets the new tables and columns on the next start."""
    db, state = _counting_db(tmp_path, monkeypatch, "upgrade.db")
    seed_data.seed_database(include_demo_data=False)

    tables = {row["name"] for row in db.fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"ride_location_points", "trip_shares", "emergency_contacts", "safety_incidents",
            "push_subscriptions"} <= tables
    wanted = {
        "driver_profiles": {"location_updated_at", "location_heading", "location_accuracy_m", "current_lat"},
        "rides": {"start_pin", "pickup_eta_minutes"},
        "driver_documents": {"expires_at"},
    }
    for table, columns in wanted.items():
        present = {row["name"] for row in db.fetchall(f"PRAGMA table_info({table})")}
        assert columns <= present, (table, columns - present)

    # restart is cheap again and leaves the data alone
    state["queries"] = 0
    seed_data.seed_database(include_demo_data=False)
    assert state["queries"] <= 6
