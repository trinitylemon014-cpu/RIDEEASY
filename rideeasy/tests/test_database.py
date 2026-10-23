from app.config import Config
from app.repositories.database import Database
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

def test_database_demo_users_exist(db):
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
    assert "admin@rideeasy.ug" in emails
    assert emails["admin@rideeasy.ug"] == "ADMIN"


def test_seed_repairs_missing_travel_fixtures(tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "TURSO_DATABASE_URL", "")
    monkeypatch.setattr(Config, "LOCAL_DB_PATH", str(tmp_path / "seed.db"))
    db = Database()
    monkeypatch.setattr(seed_data, "get_db", lambda: db)

    seed_data.seed_database()
    db.execute("DELETE FROM journey_reminders")
    db.execute("DELETE FROM confirmed_journeys")
    db.execute("DELETE FROM flight_bookings")
    db.execute("DELETE FROM flight_quotations")
    db.execute("DELETE FROM flight_requests")
    db.execute("DELETE FROM travel_companies")

    seed_data.seed_database()

    assert db.fetchone("SELECT COUNT(*) AS count FROM travel_companies")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM flight_requests")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM flight_quotations")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM flight_bookings")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM confirmed_journeys")["count"] == 1
    assert db.fetchone("SELECT COUNT(*) AS count FROM journey_reminders")["count"] == 5
