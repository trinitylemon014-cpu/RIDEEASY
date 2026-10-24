import uuid

import pytest

from app.repositories.database import get_db
from app.services.ride_dispatch_service import RideDispatchService


def _create_driver(db, suffix, online=True, rating=5.0):
    driver_id = f"usr_dispatch_{suffix}"
    db.execute(
        """INSERT INTO users (id, email, password_hash, role, full_name, phone, is_active, is_verified)
           VALUES (?, ?, 'test-hash', 'DRIVER', ?, '+256700000001', 1, 1)""",
        (driver_id, f"{driver_id}@rideeasy.test", f"Dispatch Driver {suffix}")
    )
    db.execute(
        """INSERT INTO driver_profiles
           (user_id, license_number, national_id_nin, verification_status, is_online, rating_avg)
           VALUES (?, ?, ?, 'APPROVED', ?, ?)""",
        (driver_id, f"LIC-{suffix}", f"NIN-{suffix}", int(online), rating)
    )
    db.execute(
        """INSERT INTO vehicles
           (id, driver_id, make, model, year, color, plate_number, category, capacity)
           VALUES (?, ?, 'Toyota', 'Premio', 2020, 'Blue', ?, 'ECONOMY', 4)""",
        (f"veh_{suffix}", driver_id, f"UXX {suffix}X")
    )
    return driver_id


def _create_dispatch_ride(db, passenger_id="usr_pass_01"):
    ride_id = f"ride_dispatch_{uuid.uuid4().hex[:10]}"
    db.execute(
        """INSERT INTO rides
           (id, passenger_id, category, pickup_address, pickup_lat, pickup_lng,
            destination_address, destination_lat, destination_lng, estimated_distance_km,
            estimated_fare_ugx, final_fare_ugx, status)
           VALUES (?, ?, 'ECONOMY', 'Kampala', 0.31, 32.58, 'Entebbe', 0.04, 32.44,
                   10, 10000, 10000, 'SEARCHING_FOR_DRIVER')""",
        (ride_id, passenger_id)
    )
    return ride_id


@pytest.fixture
def isolated_dispatch_drivers(db):
    previously_online = db.fetchall("SELECT user_id FROM driver_profiles WHERE is_online = 1")
    db.execute("UPDATE driver_profiles SET is_online = 0")
    yield lambda suffix, online=True, rating=5.0: _create_driver(
        db, suffix, online=online, rating=rating
    )
    db.execute("UPDATE driver_profiles SET is_online = 0 WHERE user_id LIKE 'usr_dispatch_%'")
    for profile in previously_online:
        db.execute("UPDATE driver_profiles SET is_online = 1 WHERE user_id = ?", (profile["user_id"],))


def test_dispatch_assigns_only_online_driver_and_waits_for_acceptance(db, app, isolated_dispatch_drivers):
    offline_id = isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=False)
    online_id = isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=True)
    ride_id = _create_dispatch_ride(db)

    with app.app_context():
        assigned_id = RideDispatchService.dispatch_ride(ride_id)

    assert assigned_id == online_id
    ride = db.fetchone(
        "SELECT driver_id, status, driver_response_status FROM rides WHERE id = ?",
        (ride_id,)
    )
    assert ride == {
        "driver_id": online_id,
        "status": "DRIVER_ASSIGNED",
        "driver_response_status": "PENDING"
    }
    assert db.fetchone(
        "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ? AND related_entity_id = ?",
        (offline_id, ride_id)
    )["count"] == 0
    assert db.fetchone(
        "SELECT COUNT(*) AS count FROM notifications WHERE user_id = ? AND related_entity_id = ?",
        (online_id, ride_id)
    )["count"] == 1


def test_driver_acceptance_starts_live_trip_state(client, app, db, isolated_dispatch_drivers):
    driver_id = isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=True)
    other_driver_id = isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=False)
    ride_id = _create_dispatch_ride(db)
    with app.app_context():
        assert RideDispatchService.dispatch_ride(ride_id) == driver_id

    with client.session_transaction() as browser_session:
        browser_session["user_id"] = driver_id
        browser_session["user_role"] = "DRIVER"

    offer_response = client.get("/driver/api/pending-offers")
    assert offer_response.get_json()["offers"][0]["id"] == ride_id
    assert b"do not have a live ride assigned" in client.get("/driver/active-ride").data
    dashboard = client.get("/driver/dashboard")
    assert b"1 pending trip request" in dashboard.data
    assert b"Awaiting Requests" in dashboard.data
    assert b"Accept trip" in dashboard.data
    assert b"Decline" in dashboard.data
    assert b"Review pending request" in dashboard.data
    request_page = client.get("/driver/requests")
    assert b"Assigned to you" in request_page.data
    assert b"Decline" in request_page.data

    response = client.post(f"/driver/rides/{ride_id}/accept")
    assert response.status_code == 302
    ride = db.fetchone(
        "SELECT driver_id, status, driver_response_status FROM rides WHERE id = ?",
        (ride_id,)
    )
    assert ride["driver_id"] == driver_id
    assert ride["status"] == "DRIVER_ASSIGNED"
    assert ride["driver_response_status"] == "ACCEPTED"
    assert b"Live trip updates are now active" in db.fetchone(
        "SELECT message FROM notifications WHERE user_id = 'usr_pass_01' AND related_entity_id = ? ORDER BY rowid DESC LIMIT 1",
        (ride_id,)
    )["message"].encode()
    assert b"Pickup" in client.get("/driver/active-ride").data
    live_page = client.get("/driver/active-ride")
    assert b'data-ride-id="' + ride_id.encode() + b'"' in live_page.data
    assert b"driver-live-ride-tracker" in live_page.data

    status_response = client.get(f"/api/ride-status/{ride_id}")
    assert status_response.status_code == 200
    assert status_response.get_json()["ride"]["driver_response_status"] == "ACCEPTED"

    with client.session_transaction() as browser_session:
        browser_session["user_id"] = other_driver_id
        browser_session["user_role"] = "DRIVER"
    assert client.get(f"/api/ride-status/{ride_id}").status_code == 404

    with client.session_transaction() as browser_session:
        browser_session["user_id"] = "usr_pass_01"
        browser_session["user_role"] = "PASSENGER"
    passenger_page = client.get(f"/passenger/rides/{ride_id}")
    assert b"Your driver accepted the trip" in passenger_page.data
    assert b'href="/passenger/rides/' + ride_id.encode() + b'/cancel"' in passenger_page.data
    assert client.get(f"/api/ride-status/{ride_id}").status_code == 200

    cancel_response = client.post(
        f"/passenger/rides/{ride_id}/cancel",
        data={"reason": "Passenger cancelled"},
    )
    assert cancel_response.status_code == 302
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = driver_id
        browser_session["user_role"] = "DRIVER"
    cancelled_status = client.get(f"/api/ride-status/{ride_id}")
    assert cancelled_status.get_json()["ride"]["status"] == "CANCELLED"
    assert db.fetchone(
        "SELECT title FROM notifications WHERE user_id = ? AND related_entity_id = ? ORDER BY rowid DESC LIMIT 1",
        (driver_id, ride_id),
    )["title"] == "Passenger cancelled the ride"


def test_declining_reassigns_to_another_online_driver_and_notifies_passenger(
    client, app, db, isolated_dispatch_drivers
):
    first_id = isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=True, rating=5.0)
    second_id = isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=True, rating=4.0)
    ride_id = _create_dispatch_ride(db)
    with app.app_context():
        assert RideDispatchService.dispatch_ride(ride_id) == first_id

    with client.session_transaction() as browser_session:
        browser_session["user_id"] = first_id
        browser_session["user_role"] = "DRIVER"

    response = client.post(f"/driver/rides/{ride_id}/decline")
    assert response.status_code == 302
    ride = db.fetchone(
        "SELECT driver_id, status, driver_response_status FROM rides WHERE id = ?",
        (ride_id,)
    )
    assert ride["driver_id"] == second_id
    assert ride["status"] == "DRIVER_ASSIGNED"
    assert ride["driver_response_status"] == "PENDING"
    messages = db.fetchall(
        "SELECT title, message FROM notifications WHERE user_id = 'usr_pass_01' AND related_entity_id = ?",
        (ride_id,)
    )
    assert any(row["title"] == "Driver unavailable" for row in messages)
    assert any("looking for another available driver" in row["message"] for row in messages)


def test_no_online_driver_leaves_ride_searching(db, app, isolated_dispatch_drivers):
    isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=False)
    ride_id = _create_dispatch_ride(db)
    with app.app_context():
        assigned_id = RideDispatchService.dispatch_ride(ride_id)

    assert assigned_id is None
    ride = db.fetchone(
        "SELECT driver_id, status FROM rides WHERE id = ?",
        (ride_id,)
    )
    assert ride == {"driver_id": None, "status": "SEARCHING_FOR_DRIVER"}


def test_going_online_dispatches_waiting_ride_and_notifies_driver(client, db, isolated_dispatch_drivers):
    driver_id = isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=False)
    db.execute(
        """UPDATE rides SET status = 'CANCELLED'
           WHERE driver_id IS NULL AND status IN ('REQUESTED', 'SEARCHING_FOR_DRIVER')"""
    )
    ride_id = _create_dispatch_ride(db)
    assert db.fetchone(
        """SELECT d.verification_status, v.is_active, v.is_verified
           FROM driver_profiles d JOIN vehicles v ON v.driver_id = d.user_id
           WHERE d.user_id = ?""",
        (driver_id,)
    ) == {"verification_status": "APPROVED", "is_active": 1, "is_verified": 1}

    with client.session_transaction() as browser_session:
        browser_session["user_id"] = driver_id
        browser_session["user_role"] = "DRIVER"
    response = client.post("/driver/toggle-online")

    assert response.status_code == 302
    assert db.fetchone("SELECT is_online FROM driver_profiles WHERE user_id = ?", (driver_id,))["is_online"] == 1
    ride = db.fetchone(
        "SELECT driver_id, status, driver_response_status FROM rides WHERE id = ?",
        (ride_id,)
    )
    assert ride == {
        "driver_id": driver_id,
        "status": "DRIVER_ASSIGNED",
        "driver_response_status": "PENDING",
    }
    notification = db.fetchone(
        """SELECT title, message FROM notifications
           WHERE user_id = ? AND related_entity_id = ? ORDER BY rowid DESC LIMIT 1""",
        (driver_id, ride_id)
    )
    assert notification["title"] == "New trip awaiting your response"
    assert "accept or decline" in notification["message"]


def test_going_offline_releases_pending_offer_for_another_driver(client, app, db, isolated_dispatch_drivers):
    first_id = isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=True, rating=5.0)
    second_id = isolated_dispatch_drivers(uuid.uuid4().hex[:6], online=True, rating=4.0)
    ride_id = _create_dispatch_ride(db)
    with app.app_context():
        assert RideDispatchService.dispatch_ride(ride_id) == first_id

    with client.session_transaction() as browser_session:
        browser_session["user_id"] = first_id
        browser_session["user_role"] = "DRIVER"
    response = client.post("/driver/toggle-online")

    assert response.status_code == 302
    ride = db.fetchone(
        "SELECT driver_id, status, driver_response_status FROM rides WHERE id = ?",
        (ride_id,)
    )
    assert ride["driver_id"] == second_id
    assert ride["status"] == "DRIVER_ASSIGNED"
    assert ride["driver_response_status"] == "PENDING"
    assert db.fetchone(
        "SELECT is_online FROM driver_profiles WHERE user_id = ?",
        (first_id,)
    )["is_online"] == 0
