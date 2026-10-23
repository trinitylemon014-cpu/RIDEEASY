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
