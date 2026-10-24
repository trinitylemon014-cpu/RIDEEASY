import uuid
from datetime import date

import pytest

from app.routes.driver import _years_ago
from app.services import driver_profile_service as rules

TODAY = date(2026, 10, 24)


def _valid_form(**overrides):
    form = {
        "date_of_birth": "1992-05-14",
        "years_experience": "6",
        "license_number": "dp-123456",
        "national_id_nin": "cm92012345abcd",
        "category": "ECONOMY",
        "make": "Toyota",
        "model": "Premio",
        "year": "2016",
        "color": "Silver",
        "plate_number": "uba 123x",
        "capacity": "4",
    }
    form.update(overrides)
    return form


# --------------------------------------------------------------------------- rules
def test_valid_form_is_accepted_and_normalised():
    clean, errors = rules.validate_profile(_valid_form(), today=TODAY)
    assert errors == {}
    assert clean["license_number"] == "DP-123456"
    assert clean["national_id_nin"] == "CM92012345ABCD"
    assert clean["plate_number"] == "UBA 123X"
    assert clean["years_experience"] == 6
    assert clean["capacity"] == 4


@pytest.mark.parametrize("overrides, field", [
    ({"date_of_birth": ""}, "date_of_birth"),
    ({"date_of_birth": "not-a-date"}, "date_of_birth"),
    ({"date_of_birth": "2015-01-01"}, "date_of_birth"),      # under 18
    ({"date_of_birth": "1900-01-01"}, "date_of_birth"),      # implausibly old
    ({"years_experience": "-2"}, "years_experience"),
    ({"years_experience": "abc"}, "years_experience"),
    ({"years_experience": "40"}, "years_experience"),       # more than age allows (34)
    ({"license_number": ""}, "license_number"),
    ({"license_number": "PENDING"}, "license_number"),
    ({"license_number": "<script>"}, "license_number"),
    ({"national_id_nin": "12345"}, "national_id_nin"),
    ({"national_id_nin": "XX92012345ABCD"}, "national_id_nin"),
    ({"national_id_nin": "PENDING"}, "national_id_nin"),
    ({"category": "SPACESHIP"}, "category"),
    ({"make": "A"}, "make"),
    ({"model": ""}, "model"),
    ({"color": "<b>"}, "color"),
    ({"year": "1950"}, "year"),
    ({"year": "2099"}, "year"),
    ({"plate_number": ""}, "plate_number"),
    ({"plate_number": "!!!"}, "plate_number"),
    ({"plate_number": "123456"}, "plate_number"),            # digits only
    ({"capacity": "0"}, "capacity"),
    ({"capacity": "40"}, "capacity"),                        # too many for an economy car
])
def test_invalid_values_are_rejected(overrides, field):
    _, errors = rules.validate_profile(_valid_form(**overrides), today=TODAY)
    assert field in errors


def test_bad_vehicle_type_with_huge_seat_count_does_not_crash():
    _, errors = rules.validate_profile(_valid_form(category="SPACESHIP", capacity="500"), today=TODAY)
    assert "category" in errors and "capacity" in errors


def test_boda_seat_limit_follows_vehicle_type():
    _, errors = rules.validate_profile(_valid_form(category="BODA", capacity="3"), today=TODAY)
    assert "capacity" in errors
    _, errors = rules.validate_profile(_valid_form(category="BODA", capacity="1"), today=TODAY)
    assert errors == {}


def test_age_is_exact_on_birthday():
    assert rules.age_from_dob("2008-10-24", today=TODAY) == 18
    assert rules.age_from_dob("2008-10-25", today=TODAY) == 17
    assert rules.age_from_dob("garbage") is None
    assert rules.age_from_dob(None) is None


def test_identifiers_are_masked_and_placeholders_hidden():
    assert rules.mask_identifier("CM92012345ABCD") == "CM" + "•" * 10 + "CD"
    assert rules.mask_identifier("PENDING") == "Not provided"
    assert rules.display_value("PENDING") == ""
    assert rules.display_value("DP-1") == "DP-1"


def test_years_ago_handles_leap_day():
    assert _years_ago(date(2028, 2, 29), 18) == date(2010, 2, 28)
    assert _years_ago(date(2026, 10, 24), 18) == date(2008, 10, 24)


def test_completeness_counts_steps():
    empty = rules.completeness({"license_number": "PENDING", "national_id_nin": "PENDING"}, None, 0)
    assert empty["done"] == 0 and not empty["complete"]
    full = rules.completeness(
        {"license_number": "DP-1", "national_id_nin": "CM1", "date_of_birth": "1990-01-01", "years_experience": 3},
        {"plate_number": "UBA 123X"}, 3
    )
    assert full["complete"] and full["percent"] == 100 and full["missing"] == []


# ----------------------------------------------------------------------- the page
@pytest.fixture
def new_driver(db):
    """A driver exactly as registration leaves them: placeholders and no vehicle."""
    driver_id = f"usr_prof_{uuid.uuid4().hex[:8]}"
    db.execute(
        """INSERT INTO users (id, email, password_hash, role, full_name, phone, is_active, is_verified)
           VALUES (?, ?, 'test-hash', 'DRIVER', 'Profile Tester', '+256700000009', 1, 0)""",
        (driver_id, f"{driver_id}@rideeasy.test"),
    )
    db.execute(
        """INSERT INTO driver_profiles (user_id, license_number, national_id_nin, verification_status)
           VALUES (?, 'PENDING', 'PENDING', 'PENDING')""",
        (driver_id,),
    )
    yield driver_id
    db.execute("DELETE FROM audit_logs WHERE user_id = ?", (driver_id,))
    db.execute("DELETE FROM vehicles WHERE driver_id = ?", (driver_id,))
    db.execute("DELETE FROM driver_profiles WHERE user_id = ?", (driver_id,))
    db.execute("DELETE FROM users WHERE id = ?", (driver_id,))


def _login(client, driver_id):
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = driver_id
        browser_session["user_role"] = "DRIVER"


def _token(client):
    client.get("/driver/profile")  # rendering the page puts the CSRF token in the session
    with client.session_transaction() as browser_session:
        return browser_session["payment_csrf_token"]


def _post(client, form, token=None):
    data = dict(form)
    data["csrf_token"] = token if token is not None else _token(client)
    return client.post("/driver/profile", data=data)


def _plate():
    """A random, valid-looking Ugandan plate such as 'UKP 482T' (unique enough per test run)."""
    n = uuid.uuid4().int
    letters = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    return f"U{letters[n % 24]}{letters[(n >> 8) % 24]} {(n >> 16) % 900 + 100}{letters[(n >> 24) % 24]}"


def test_new_driver_sees_empty_form_without_placeholders(client, new_driver):
    _login(client, new_driver)
    response = client.get("/driver/profile")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "My work profile" in page
    assert "PENDING" not in page.split("<form", 1)[1].split("</form>", 1)[0]
    assert "Save your vehicle details above first" in page


def test_first_save_creates_vehicle_and_goes_to_photos(client, db, new_driver):
    _login(client, new_driver)
    plate = _plate()
    response = _post(client, _valid_form(plate_number=plate))
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/driver/vehicle-photos")

    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (new_driver,))
    assert profile["license_number"] == "DP-123456"
    assert profile["national_id_nin"] == "CM92012345ABCD"
    assert profile["date_of_birth"] == "1992-05-14"
    assert profile["years_experience"] == 6
    assert profile["verification_status"] == "PENDING"  # admin still has to approve

    vehicle = db.fetchone("SELECT * FROM vehicles WHERE driver_id = ?", (new_driver,))
    assert vehicle["plate_number"] == plate
    assert vehicle["category"] == "ECONOMY" and vehicle["capacity"] == 4

    audit = db.fetchone("SELECT details FROM audit_logs WHERE user_id = ?", (new_driver,))
    assert audit["details"] == "Work profile updated"
    assert "CM92012345" not in str(audit)  # ID numbers never go into the audit log

    page = client.get("/driver/profile").get_data(as_text=True)
    assert "Toyota" in page and "DP-123456" in page


def test_invalid_save_returns_errors_and_stores_nothing(client, db, new_driver):
    _login(client, new_driver)
    response = _post(client, _valid_form(national_id_nin="123", date_of_birth="2015-01-01"))
    assert response.status_code == 400
    page = response.get_data(as_text=True)
    assert "A NIN has 14 characters" in page
    assert "at least 18 years old" in page
    assert db.fetchone("SELECT 1 AS x FROM vehicles WHERE driver_id = ?", (new_driver,)) is None
    assert db.fetchone("SELECT license_number FROM driver_profiles WHERE user_id = ?", (new_driver,))["license_number"] == "PENDING"


def test_post_without_csrf_token_is_refused(client, db, new_driver):
    _login(client, new_driver)
    response = _post(client, _valid_form(plate_number=_plate()), token="wrong-token")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/driver/profile")
    assert db.fetchone("SELECT 1 AS x FROM vehicles WHERE driver_id = ?", (new_driver,)) is None


def test_plate_already_used_by_another_driver_is_rejected(client, db, new_driver):
    other_id = f"usr_prof_{uuid.uuid4().hex[:8]}"
    plate = _plate()
    db.execute(
        """INSERT INTO users (id, email, password_hash, role, full_name, phone, is_active, is_verified)
           VALUES (?, ?, 'x', 'DRIVER', 'Other Driver', '+256700000008', 1, 1)""",
        (other_id, f"{other_id}@rideeasy.test"),
    )
    db.execute(
        """INSERT INTO vehicles (id, driver_id, make, model, year, color, plate_number, category, capacity)
           VALUES (?, ?, 'Honda', 'Fit', 2015, 'Red', ?, 'ECONOMY', 4)""",
        (f"veh_{uuid.uuid4().hex[:8]}", other_id, plate),
    )
    try:
        _login(client, new_driver)
        response = _post(client, _valid_form(plate_number=plate))
        assert response.status_code == 400
        assert "already registered to another driver" in response.get_data(as_text=True)
        assert db.fetchone("SELECT 1 AS x FROM vehicles WHERE driver_id = ?", (new_driver,)) is None
    finally:
        db.execute("DELETE FROM vehicles WHERE driver_id = ?", (other_id,))
        db.execute("DELETE FROM users WHERE id = ?", (other_id,))


def test_approved_driver_changing_plate_goes_back_to_review(client, db, new_driver):
    _login(client, new_driver)
    plate = _plate()
    _post(client, _valid_form(plate_number=plate))
    db.execute("UPDATE driver_profiles SET verification_status = 'APPROVED', is_online = 1 WHERE user_id = ?", (new_driver,))
    db.execute("UPDATE users SET is_verified = 1 WHERE id = ?", (new_driver,))

    # Cosmetic change: stays approved and online.
    response = _post(client, _valid_form(plate_number=plate, color="Black"))
    assert response.status_code == 302
    profile = db.fetchone("SELECT verification_status, is_online FROM driver_profiles WHERE user_id = ?", (new_driver,))
    assert profile == {"verification_status": "APPROVED", "is_online": 1}

    # Plate change: needs a fresh admin review and the driver goes offline.
    response = _post(client, _valid_form(plate_number=_plate(), color="Black"))
    assert response.status_code == 302
    profile = db.fetchone("SELECT verification_status, is_online FROM driver_profiles WHERE user_id = ?", (new_driver,))
    assert profile == {"verification_status": "PENDING", "is_online": 0}
    assert db.fetchone("SELECT is_verified FROM users WHERE id = ?", (new_driver,))["is_verified"] == 0
    last = db.fetchall("SELECT details FROM audit_logs WHERE user_id = ? ORDER BY rowid DESC", (new_driver,))[0]
    assert "admin review" in last["details"]


def test_approved_driver_filling_in_missing_details_stays_approved(client, db, new_driver):
    # An approved driver from before this page existed has no date of birth or vehicle on file.
    db.execute(
        """UPDATE driver_profiles SET verification_status = 'APPROVED', is_online = 1,
                  license_number = 'OLD-LIC-1', national_id_nin = 'CM00000000OLDX' WHERE user_id = ?""",
        (new_driver,),
    )
    _login(client, new_driver)
    response = _post(client, _valid_form(license_number="OLD-LIC-1", national_id_nin="CM00000000OLDX",
                                         plate_number=_plate()))
    assert response.status_code == 302
    profile = db.fetchone("SELECT verification_status, is_online, date_of_birth FROM driver_profiles WHERE user_id = ?", (new_driver,))
    assert profile == {"verification_status": "APPROVED", "is_online": 1, "date_of_birth": "1992-05-14"}


def test_passenger_cannot_open_driver_profile(client):
    client.get("/auth/demo/passenger", follow_redirects=True)
    response = client.get("/driver/profile")
    assert response.status_code in (302, 403)


def test_dashboard_prompts_until_profile_is_complete(client, new_driver):
    _login(client, new_driver)
    page = client.get("/driver/dashboard").get_data(as_text=True)
    assert "Finish your work profile" in page
    assert 'href="/driver/profile"' in page and 'href="/driver/vehicle-photos"' in page


def test_verification_page_masks_the_nin(client, db, new_driver):
    _login(client, new_driver)
    _post(client, _valid_form(plate_number=_plate()))
    page = client.get("/driver/verification").get_data(as_text=True)
    assert "CM92012345ABCD" not in page
    assert "CM" + "•" * 10 + "CD" in page
    assert f"{rules.age_from_dob('1992-05-14')} years" in page


def test_admin_driver_list_shows_the_new_details(client, db, new_driver):
    _login(client, new_driver)
    _post(client, _valid_form(plate_number=_plate()))
    admin = db.fetchone("SELECT id FROM users WHERE role = 'ADMIN' LIMIT 1")
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = admin["id"]
        browser_session["user_role"] = "ADMIN"
    response = client.get("/admin/drivers")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "DP-123456" in page and "Photos 0/3" in page and "yrs driving" in page
