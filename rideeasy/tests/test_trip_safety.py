"""Trip PIN, trip sharing, SOS alerts, emergency contacts and admin review."""
import re
import uuid

import pytest

from app.services.realtime_service import RealtimeService
from app.services.safety_service import SafetyError, SafetyService
from app.services.sms_service import SmsService

XHR = {"X-Requested-With": "RideEasy"}


@pytest.fixture(autouse=True)
def clean_state():
    RealtimeService.reset()
    SafetyService.reset_pin_state()
    yield
    RealtimeService.reset()
    SafetyService.reset_pin_state()


def sign_in(client, user_id, role):
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = user_id
        browser_session["user_role"] = role


def csrf_token(client):
    with client.session_transaction() as browser_session:
        return browser_session.get("payment_csrf_token", "")


@pytest.fixture
def people(db):
    """A passenger, a driver with a vehicle and a position, and an admin."""
    suffix = uuid.uuid4().hex[:8]
    ids = {"passenger": f"usr_sp_{suffix}", "driver": f"usr_sd_{suffix}", "admin": f"usr_sa_{suffix}",
           "stranger": f"usr_sx_{suffix}"}
    rows = (
        (ids["passenger"], "PASSENGER", "Grace Namukasa", "+256700111111"),
        (ids["driver"], "DRIVER", "Moses Okello", "+256700222222"),
        (ids["admin"], "ADMIN", "Safety Admin", "+256700333333"),
        (ids["stranger"], "PASSENGER", "Other Person", "+256700444444"),
    )
    for user_id, role, name, phone in rows:
        db.execute(
            """INSERT INTO users (id, email, password_hash, role, full_name, phone, is_active, is_verified)
               VALUES (?, ?, 'x', ?, ?, ?, 1, 1)""",
            (user_id, f"{user_id}@rideeasy.test", role, name, phone),
        )
    db.execute(
        """INSERT INTO driver_profiles (user_id, license_number, national_id_nin, verification_status, is_online,
                  current_lat, current_lng, location_updated_at)
           VALUES (?, ?, ?, 'APPROVED', 0, 0.3200, 32.5900, CURRENT_TIMESTAMP)""",
        (ids["driver"], f"L{suffix}", f"N{suffix}"),
    )
    db.execute(
        """INSERT INTO vehicles (id, driver_id, make, model, year, color, plate_number, category, capacity)
           VALUES (?, ?, 'Toyota', 'Premio', 2020, 'Blue', ?, 'ECONOMY', 4)""",
        (f"veh_{suffix}", ids["driver"], f"UBZ{suffix[:3].upper()}"),
    )
    yield ids
    db.execute("UPDATE users SET is_active = 0 WHERE id = ?", (ids["admin"],))   # keep other tests' admin alerts quiet


def make_ride(db, people, status="DRIVER_ARRIVING"):
    ride_id = f"ride_sf_{uuid.uuid4().hex[:8]}"
    db.execute(
        """INSERT INTO rides
           (id, passenger_id, driver_id, category, pickup_address, pickup_lat, pickup_lng,
            destination_address, destination_lat, destination_lng, estimated_distance_km,
            estimated_fare_ugx, final_fare_ugx, status, driver_response_status)
           VALUES (?, ?, ?, 'ECONOMY', 'Kampala Road', 0.3136, 32.5811, 'Entebbe Airport', 0.0424, 32.4435,
                   10, 10000, 10000, ?, 'ACCEPTED')""",
        (ride_id, people["passenger"], people["driver"], status),
    )
    return ride_id


# -------------------------------------------------------------------- trip PIN
def test_pin_is_created_once_and_has_four_digits(app, db, people):
    ride_id = make_ride(db, people)
    with app.app_context():
        pin = SafetyService.ensure_pin(ride_id)
        assert re.fullmatch(r"\d{4}", pin)
        assert SafetyService.ensure_pin(ride_id) == pin


def test_wrong_pin_is_rejected_and_repeated_guessing_locks_the_ride(app, db, people):
    ride_id = make_ride(db, people)
    with app.app_context():
        SafetyService.ensure_pin(ride_id)
        ride = db.fetchone("SELECT * FROM rides WHERE id = ?", (ride_id,))
        wrong = "0000" if ride["start_pin"] != "0000" else "1111"
        assert SafetyService.verify_pin(ride, "") == (False, "That PIN is not correct. Ask the passenger for the 4-digit trip PIN.")
        for _ in range(4):
            assert SafetyService.verify_pin(ride, wrong)[0] is False
        locked, message = SafetyService.verify_pin(ride, ride["start_pin"])      # even the right PIN is refused
        assert locked is False and "Too many" in message
    assert db.fetchone(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND title LIKE 'Wrong trip PIN%'",
        (people["passenger"],),
    )["c"] == 1


def test_correct_pin_is_accepted_and_clears_earlier_mistakes(app, db, people):
    ride_id = make_ride(db, people)
    with app.app_context():
        SafetyService.ensure_pin(ride_id)
        ride = db.fetchone("SELECT * FROM rides WHERE id = ?", (ride_id,))
        wrong = "0000" if ride["start_pin"] != "0000" else "1111"
        SafetyService.verify_pin(ride, wrong)
        assert SafetyService.verify_pin(ride, ride["start_pin"]) == (True, "")
        assert SafetyService.verify_pin(ride, wrong)[1].startswith("That PIN")      # counter was reset


def test_rides_without_a_pin_and_a_disabled_setting_do_not_block_starting(app, db, people):
    ride_id = make_ride(db, people)
    ride = db.fetchone("SELECT * FROM rides WHERE id = ?", (ride_id,))
    with app.app_context():
        assert SafetyService.verify_pin(ride, "")[0] is True          # old ride, no PIN stored
        SafetyService.ensure_pin(ride_id)
        ride = db.fetchone("SELECT * FROM rides WHERE id = ?", (ride_id,))
        app.config["REQUIRE_TRIP_PIN"] = False
        try:
            assert SafetyService.verify_pin(ride, "")[0] is True
        finally:
            app.config["REQUIRE_TRIP_PIN"] = True


def test_driver_cannot_start_the_trip_without_the_passengers_pin(client, db, people):
    ride_id = make_ride(db, people, status="DRIVER_ARRIVED")
    pin = db.fetchone("SELECT start_pin FROM rides WHERE id = ?", (ride_id,))["start_pin"] or None
    if pin is None:
        db.execute("UPDATE rides SET start_pin = '4821' WHERE id = ?", (ride_id,))
        pin = "4821"
    sign_in(client, people["driver"], "DRIVER")

    client.post(f"/driver/rides/{ride_id}/status", data={"status": "TRIP_STARTED"})
    assert db.fetchone("SELECT status FROM rides WHERE id = ?", (ride_id,))["status"] == "DRIVER_ARRIVED"
    wrong = "0000" if pin != "0000" else "1111"
    client.post(f"/driver/rides/{ride_id}/status", data={"status": "TRIP_STARTED", "pin": wrong})
    assert db.fetchone("SELECT status FROM rides WHERE id = ?", (ride_id,))["status"] == "DRIVER_ARRIVED"
    client.post(f"/driver/rides/{ride_id}/status", data={"status": "TRIP_STARTED", "pin": pin})
    assert db.fetchone("SELECT status FROM rides WHERE id = ?", (ride_id,))["status"] == "TRIP_STARTED"


def test_passenger_sees_the_pin_on_the_ride_page_and_driver_page_asks_for_it(client, db, people):
    ride_id = make_ride(db, people, status="DRIVER_ARRIVED")
    sign_in(client, people["passenger"], "PASSENGER")
    page = client.get(f"/passenger/rides/{ride_id}").get_data(as_text=True)
    pin = db.fetchone("SELECT start_pin FROM rides WHERE id = ?", (ride_id,))["start_pin"]
    assert re.fullmatch(r"\d{4}", pin) and f">{pin}<" in page
    assert "Share my trip" in page and "SOS emergency" in page and 'id="trip-map"' in page

    sign_in(client, people["driver"], "DRIVER")
    driver_page = client.get("/driver/active-ride").get_data(as_text=True)
    assert 'name="pin"' in driver_page and pin not in driver_page
    assert "SOS emergency" in driver_page and "Navigate to pickup" in driver_page


# ----------------------------------------------------------------- trip sharing
def test_only_the_passenger_of_an_active_trip_can_share_it(app, db, people):
    active = make_ride(db, people)
    finished = make_ride(db, people, status="COMPLETED")
    with app.test_request_context():
        link = SafetyService.create_share(active, people["passenger"])
        assert SafetyService.create_share(active, people["passenger"])["token"] == link["token"]    # idempotent
        with pytest.raises(SafetyError):
            SafetyService.create_share(active, people["stranger"])
        with pytest.raises(SafetyError):
            SafetyService.create_share(finished, people["passenger"])


def test_shared_view_shows_first_names_and_live_position_but_no_phone_numbers(app, db, people):
    ride_id = make_ride(db, people)
    with app.test_request_context():
        token = SafetyService.create_share(ride_id, people["passenger"])["token"]
        trip = SafetyService.get_shared_trip(token)
    assert trip["passenger_first_name"] == "Grace" and trip["driver_first_name"] == "Moses"
    assert trip["active"] and trip["driver_location"]["target"] == "pickup"
    assert trip["plate_number"] and "Toyota" in trip["vehicle"]
    flat = str(trip)
    for secret in ("+256700", "Namukasa", "Okello", "@rideeasy"):
        assert secret not in flat


def test_share_link_stops_working_when_revoked_or_expired_and_hides_position_after_the_trip(app, db, people):
    ride_id = make_ride(db, people)
    with app.test_request_context():
        token = SafetyService.create_share(ride_id, people["passenger"])["token"]
        assert SafetyService.get_shared_trip("not-a-real-token") is None
        db.execute("UPDATE rides SET status = 'COMPLETED' WHERE id = ?", (ride_id,))
        ended = SafetyService.get_shared_trip(token)
        assert ended["active"] is False and ended["driver_location"] is None
        assert SafetyService.revoke_shares(ride_id, people["stranger"]) == 0       # not their trip
        assert SafetyService.revoke_shares(ride_id, people["passenger"]) == 1
        assert SafetyService.get_shared_trip(token) is None
        fresh = SafetyService.create_share(make_ride(db, people), people["passenger"])
        db.execute("UPDATE trip_shares SET expires_at = datetime(CURRENT_TIMESTAMP, '-1 minute') WHERE token = ?", (fresh["token"],))
        assert SafetyService.get_shared_trip(fresh["token"]) is None


def test_public_share_pages_work_without_signing_in(client, app, db, people, monkeypatch):
    ride_id = make_ride(db, people)
    sign_in(client, people["passenger"], "PASSENGER")
    created = client.post(f"/trip-safety/rides/{ride_id}/share", headers=XHR).get_json()
    assert created["success"] and "/track/" in created["url"]
    token = created["url"].rsplit("/", 1)[1]

    with client.session_transaction() as browser_session:      # a friend with the link: no session at all
        browser_session.clear()
    page = client.get(f"/track/{token}")
    assert page.status_code == 200
    assert page.headers["X-Robots-Tag"] == "noindex, nofollow" and page.headers["Referrer-Policy"] == "no-referrer"
    assert page.headers["Cache-Control"] == "no-store"
    body = page.get_data(as_text=True)
    assert "Grace" in body and "Moses" in body and "+256700" not in body

    status = client.get(f"/track/{token}/status.json").get_json()
    assert status["trip"]["driver_location"]["eta_minutes"] >= 1

    assert client.get("/track/short").status_code == 404
    assert client.get("/track/" + "a" * 32).status_code == 404
    assert client.get("/track/" + "a" * 32 + "/status.json").status_code == 404

    monkeypatch.setattr("app.routes.share.serve_tile", lambda z, x, y: ("tile", 200))
    assert client.get(f"/track/{token}/tiles/3/4/5.png").status_code == 200
    assert client.get("/track/" + "b" * 32 + "/tiles/3/4/5.png").status_code == 404

    sign_in(client, people["passenger"], "PASSENGER")
    assert client.post(f"/trip-safety/rides/{ride_id}/share/revoke", headers=XHR).status_code == 200
    with client.session_transaction() as browser_session:
        browser_session.clear()
    assert client.get(f"/track/{token}").status_code == 404


def test_share_endpoints_reject_other_passengers_and_requests_without_the_header(client, db, people):
    ride_id = make_ride(db, people)
    sign_in(client, people["stranger"], "PASSENGER")
    assert client.post(f"/trip-safety/rides/{ride_id}/share", headers=XHR).status_code == 400
    sign_in(client, people["passenger"], "PASSENGER")
    assert client.post(f"/trip-safety/rides/{ride_id}/share").status_code == 400
    sign_in(client, people["driver"], "DRIVER")
    assert client.post(f"/trip-safety/rides/{ride_id}/share", headers=XHR).status_code == 403


# -------------------------------------------------------------------------- SOS
@pytest.fixture
def sent_sms(monkeypatch):
    sent = []
    monkeypatch.setattr(SmsService, "send_safety_sms", staticmethod(lambda phone, text: sent.append((phone, text)) or "SENT"))
    return sent


def test_passenger_sos_alerts_admins_texts_contacts_and_creates_a_tracking_link(client, db, people, sent_sms):
    ride_id = make_ride(db, people, status="TRIP_STARTED")
    sign_in(client, people["passenger"], "PASSENGER")
    page = client.get("/trip-safety/contacts")
    assert page.status_code == 200
    for name, phone in (("Mum", "+256 772 000111"), ("Brother", "0701234567")):
        client.post("/trip-safety/contacts", data={"name": name, "phone": phone, "csrf_token": csrf_token(client)})

    response = client.post(f"/trip-safety/rides/{ride_id}/sos", json={"lat": 0.3101, "lng": 32.5822, "message": "Driver is off route"}, headers=XHR)
    data = response.get_json()
    assert response.status_code == 200 and data["success"] and data["contacts_notified"] == 2
    assert "/track/" in data["share_url"] and data["emergency_number"] == "999"

    assert len(sent_sms) == 2
    text = sent_sms[0][1]
    assert "Grace" in text and "maps.google.com/?q=0.31010,32.58220" in text and data["share_url"] in text
    incident = db.fetchone("SELECT * FROM safety_incidents WHERE id = ?", (data["incident_id"],))
    assert incident["status"] == "OPEN" and incident["reporter_role"] == "PASSENGER" and incident["message"] == "Driver is off route"
    assert db.fetchone("SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'SOS_TRIGGERED' AND resource_id = ?", (ride_id,))["c"] == 1
    assert db.fetchone(
        "SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND related_entity_id = ? AND title LIKE 'SOS alert%'",
        (people["admin"], ride_id),
    )["c"] == 1
    # the driver is deliberately not told, to avoid escalating the situation
    assert db.fetchone("SELECT COUNT(*) AS c FROM notifications WHERE user_id = ? AND title LIKE 'SOS%'", (people["driver"],))["c"] == 0


def test_pressing_sos_twice_quickly_does_not_spam_contacts(client, db, people, sent_sms):
    ride_id = make_ride(db, people, status="TRIP_STARTED")
    sign_in(client, people["passenger"], "PASSENGER")
    client.post("/trip-safety/contacts", data={"name": "Mum", "phone": "+256772000111", "csrf_token": csrf_token(client) or (client.get("/trip-safety/contacts") and csrf_token(client))})
    first = client.post(f"/trip-safety/rides/{ride_id}/sos", json={}, headers=XHR).get_json()
    second = client.post(f"/trip-safety/rides/{ride_id}/sos", json={}, headers=XHR).get_json()
    assert second["duplicate"] is True and second["incident_id"] == first["incident_id"]
    assert len(sent_sms) <= 1


def test_driver_sos_uses_the_drivers_last_known_position(client, db, people, sent_sms):
    ride_id = make_ride(db, people, status="DRIVER_ARRIVED")
    sign_in(client, people["driver"], "DRIVER")
    data = client.post(f"/trip-safety/rides/{ride_id}/sos", json={}, headers=XHR).get_json()
    incident = db.fetchone("SELECT * FROM safety_incidents WHERE id = ?", (data["incident_id"],))
    assert incident["reporter_role"] == "DRIVER" and incident["lat"] == 0.32 and incident["lng"] == 32.59
    assert data["share_url"] is None      # only a passenger's trip can be shared


def test_sos_is_limited_to_people_on_an_active_trip(client, db, people, sent_sms):
    active = make_ride(db, people)
    finished = make_ride(db, people, status="COMPLETED")
    sign_in(client, people["stranger"], "PASSENGER")
    assert client.post(f"/trip-safety/rides/{active}/sos", json={}, headers=XHR).status_code == 400
    sign_in(client, people["passenger"], "PASSENGER")
    ended = client.post(f"/trip-safety/rides/{finished}/sos", json={}, headers=XHR)
    assert ended.status_code == 400 and "999" in ended.get_json()["error"]
    assert client.post(f"/trip-safety/rides/{active}/sos", json={}).status_code == 400       # missing header
    assert client.post("/trip-safety/rides/no_such_ride/sos", json={}, headers=XHR).status_code == 400


def test_sos_endpoint_is_rate_limited(client, db, people, sent_sms):
    ride_id = make_ride(db, people)
    sign_in(client, people["passenger"], "PASSENGER")
    codes = [client.post(f"/trip-safety/rides/{ride_id}/sos", json={}, headers=XHR).status_code for _ in range(6)]
    assert codes[0] == 200 and 429 in codes


def test_safety_sms_reports_not_configured_without_calling_the_network(app):
    app.config.update(EGOSMS_API_URL="", EGOSMS_API_KEY="")
    with app.app_context():
        assert SmsService.send_safety_sms("+256700000000", "test") == "NOT_CONFIGURED"


# ------------------------------------------------------------ emergency contacts
def test_contact_validation_limit_and_ownership(app, db, people):
    with app.app_context():
        user = people["passenger"]
        for name, phone in (("", "+256700000000"), ("A" * 81, "+256700000000"), ("Ann", "abc"), ("Ann", "12")):
            with pytest.raises(SafetyError):
                SafetyService.add_contact(user, name, phone)
        for number in range(5):
            SafetyService.add_contact(user, f"Person {number}", f"+25670000000{number}")
        with pytest.raises(SafetyError):
            SafetyService.add_contact(user, "Sixth", "+256700000009")
        first = SafetyService.list_contacts(user)[0]["id"]
        assert SafetyService.delete_contact(people["stranger"], first) == 0
        assert SafetyService.delete_contact(user, first) == 1
        assert len(SafetyService.list_contacts(user)) == 4


def test_contacts_page_requires_a_valid_csrf_token(client, db, people):
    sign_in(client, people["passenger"], "PASSENGER")
    client.get("/trip-safety/contacts")
    client.post("/trip-safety/contacts", data={"name": "Mum", "phone": "+256772000111"})
    assert db.fetchone(
        "SELECT COUNT(*) AS c FROM emergency_contacts WHERE user_id = ?", (people["passenger"],))["c"] == 0
    client.post("/trip-safety/contacts", data={"name": "Mum", "phone": "+256772000111", "csrf_token": csrf_token(client)})
    contact = db.fetchone("SELECT id, name FROM emergency_contacts WHERE user_id = ?", (people["passenger"],))
    assert contact["name"] == "Mum"
    client.post(f"/trip-safety/contacts/{contact['id']}/delete", data={})
    assert db.fetchone("SELECT COUNT(*) AS c FROM emergency_contacts WHERE user_id = ?", (people["passenger"],))["c"] == 1
    client.post(f"/trip-safety/contacts/{contact['id']}/delete", data={"csrf_token": csrf_token(client)})
    assert db.fetchone("SELECT COUNT(*) AS c FROM emergency_contacts WHERE user_id = ?", (people["passenger"],))["c"] == 0


def test_safety_pages_are_for_riders_and_drivers_only(client, people):
    assert client.get("/trip-safety/contacts").status_code == 302
    sign_in(client, people["admin"], "ADMIN")
    assert client.get("/trip-safety/contacts").status_code == 403


# ---------------------------------------------------------------- admin review
def test_admin_can_review_and_resolve_safety_alerts(client, db, people, sent_sms):
    ride_id = make_ride(db, people, status="TRIP_STARTED")
    sign_in(client, people["passenger"], "PASSENGER")
    incident_id = client.post(f"/trip-safety/rides/{ride_id}/sos", json={"lat": 0.31, "lng": 32.58}, headers=XHR).get_json()["incident_id"]

    sign_in(client, people["passenger"], "PASSENGER")
    assert client.get("/admin/safety").status_code == 403

    sign_in(client, people["admin"], "ADMIN")
    page = client.get("/admin/safety").get_data(as_text=True)
    assert incident_id in page and "Moses Okello" in page and "maps?q=0.31,32.58" in page
    assert client.get("/admin/safety?status=bogus").status_code == 200

    client.post(f"/admin/safety/{incident_id}/resolve", data={"note": "Called rider"})              # no CSRF token
    assert db.fetchone("SELECT status FROM safety_incidents WHERE id = ?", (incident_id,))["status"] == "OPEN"
    client.post(f"/admin/safety/{incident_id}/resolve", data={"note": "Called rider, all safe", "csrf_token": csrf_token(client)})
    resolved = db.fetchone("SELECT * FROM safety_incidents WHERE id = ?", (incident_id,))
    assert resolved["status"] == "RESOLVED" and resolved["resolved_by"] == people["admin"]
    assert resolved["resolution_note"] == "Called rider, all safe"
    assert db.fetchone("SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'SOS_RESOLVED' AND resource_id = ?", (incident_id,))["c"] == 1
    assert incident_id not in client.get("/admin/safety").get_data(as_text=True)               # no longer in the open list
    assert "Called rider, all safe" in client.get("/admin/safety?status=RESOLVED").get_data(as_text=True)
    client.post(f"/admin/safety/{incident_id}/resolve", data={"note": "again", "csrf_token": csrf_token(client)})
    assert db.fetchone("SELECT resolution_note FROM safety_incidents WHERE id = ?", (incident_id,))["resolution_note"] == "Called rider, all safe"
