"""Distance-based dispatch, live driver location, real-time events, ETA and web push."""
import base64
import http.server
import json
import threading
import uuid

import pytest

from app.repositories.database import get_db
from app.services.driver_location_service import DriverLocationService
from app.services.geo import eta_minutes, haversine_km, valid_point
from app.services.notification_service import NotificationService
from app.services.push_service import PushService
from app.services.realtime_service import RealtimeService
from app.services.ride_dispatch_service import RideDispatchService

PICKUP = (0.3136, 32.5811)          # Kampala
KM = 1 / 111.0                      # about one kilometre in degrees of latitude


def at_km(km, lat=PICKUP[0], lng=PICKUP[1]):
    return lat + km * KM, lng


@pytest.fixture(autouse=True)
def clean_state():
    RealtimeService.reset()
    DriverLocationService.reset()
    yield
    RealtimeService.reset()
    DriverLocationService.reset()


@pytest.fixture
def make_driver(db):
    previously_online = db.fetchall("SELECT user_id FROM driver_profiles WHERE is_online = 1")
    db.execute("UPDATE driver_profiles SET is_online = 0")
    created = []

    def factory(km=None, age_seconds=5, rating=5.0, trips=0, online=True, lat=None, lng=None):
        suffix = uuid.uuid4().hex[:8]
        driver_id = f"usr_live_{suffix}"
        db.execute(
            """INSERT INTO users (id, email, password_hash, role, full_name, phone, is_active, is_verified)
               VALUES (?, ?, 'x', 'DRIVER', ?, '+256700000009', 1, 1)""",
            (driver_id, f"{driver_id}@rideeasy.test", f"Live Driver {suffix}"),
        )
        position = (lat, lng) if lat is not None else (at_km(km) if km is not None else (None, None))
        db.execute(
            """INSERT INTO driver_profiles
               (user_id, license_number, national_id_nin, verification_status, is_online, rating_avg,
                total_trips, current_lat, current_lng, location_updated_at)
               VALUES (?, ?, ?, 'APPROVED', ?, ?, ?, ?, ?,
                       CASE WHEN ? IS NULL THEN NULL ELSE datetime(CURRENT_TIMESTAMP, ?) END)""",
            (driver_id, f"L{suffix}", f"N{suffix}", int(online), rating, trips,
             position[0], position[1], position[0], f"-{age_seconds} seconds"),
        )
        db.execute(
            """INSERT INTO vehicles (id, driver_id, make, model, year, color, plate_number, category, capacity)
               VALUES (?, ?, 'Toyota', 'Premio', 2020, 'Blue', ?, 'ECONOMY', 4)""",
            (f"veh_{suffix}", driver_id, f"UL{suffix[:5].upper()}"),
        )
        created.append(driver_id)
        return driver_id

    yield factory
    for driver_id in created:
        db.execute("UPDATE driver_profiles SET is_online = 0 WHERE user_id = ?", (driver_id,))
    for profile in previously_online:
        db.execute("UPDATE driver_profiles SET is_online = 1 WHERE user_id = ?", (profile["user_id"],))


def make_ride(db, status="SEARCHING_FOR_DRIVER", driver_id=None, response="PENDING", pickup=PICKUP,
              passenger_id="usr_pass_01", minutes_old=0):
    ride_id = f"ride_live_{uuid.uuid4().hex[:8]}"
    db.execute(
        """INSERT INTO rides
           (id, passenger_id, driver_id, category, pickup_address, pickup_lat, pickup_lng,
            destination_address, destination_lat, destination_lng, estimated_distance_km,
            estimated_fare_ugx, final_fare_ugx, status, driver_response_status, created_at)
           VALUES (?, ?, ?, 'ECONOMY', 'Kampala Road', ?, ?, 'Entebbe', 0.0424, 32.4435, 10,
                   10000, 10000, ?, ?, datetime(CURRENT_TIMESTAMP, ?))""",
        (ride_id, passenger_id, driver_id, pickup[0], pickup[1], status, response, f"-{minutes_old} minutes"),
    )
    return ride_id


def dispatch(app, ride_id, **kwargs):
    with app.app_context():
        return RideDispatchService.dispatch_ride(ride_id, **kwargs)


# ------------------------------------------------------------------ geo helpers
def test_geo_helpers():
    assert valid_point(0.3, 32.5) and not valid_point(0, 0) and not valid_point(91, 10)
    assert not valid_point("x", 1) and not valid_point(float("nan"), 1) and not valid_point(None, None)
    assert 110 < haversine_km(0, 0, 1, 0) < 112
    assert eta_minutes(5, 25) > eta_minutes(1, 25) >= 1
    assert eta_minutes(0, 25) == 1.0


# -------------------------------------------------------- distance-based matching
def test_nearest_driver_is_offered_first_then_next_nearest(app, db, make_driver):
    app.config["DISPATCH_REQUIRE_DRIVER_LOCATION"] = True
    far, near, middle = make_driver(km=9), make_driver(km=1), make_driver(km=4)
    ride_id = make_ride(db)

    assert dispatch(app, ride_id) == near
    with app.app_context():
        assert RideDispatchService.decline_offer(ride_id, near)
    assert dispatch(app, ride_id) == middle
    with app.app_context():
        assert RideDispatchService.decline_offer(ride_id, middle)
    assert dispatch(app, ride_id) == far


def test_driver_outside_radius_is_never_offered(app, db, make_driver):
    app.config["DISPATCH_REQUIRE_DRIVER_LOCATION"] = True
    make_driver(km=40)
    assert dispatch(app, make_ride(db)) is None


def test_stale_or_missing_location_is_skipped_when_location_is_required(app, db, make_driver):
    app.config["DISPATCH_REQUIRE_DRIVER_LOCATION"] = True
    make_driver(km=1, age_seconds=1000)       # shared location long ago
    make_driver()                              # never shared a location
    assert dispatch(app, make_ride(db)) is None
    fresh = make_driver(km=2, age_seconds=10)
    assert dispatch(app, make_ride(db)) == fresh


def test_unlocated_drivers_rank_last_when_location_is_optional(app, db, make_driver):
    app.config["DISPATCH_REQUIRE_DRIVER_LOCATION"] = False
    unlocated = make_driver(rating=5.0)
    located = make_driver(km=10, rating=3.0)
    ride_id = make_ride(db)
    assert dispatch(app, ride_id) == located
    with app.app_context():
        RideDispatchService.decline_offer(ride_id, located)
    assert dispatch(app, ride_id) == unlocated


def test_drivers_in_the_same_half_kilometre_are_ordered_by_rating(app, db, make_driver):
    app.config["DISPATCH_REQUIRE_DRIVER_LOCATION"] = True
    slightly_closer = make_driver(km=1.00, rating=3.5)
    better_rated = make_driver(km=1.10, rating=4.9)
    assert dispatch(app, make_ride(db)) == better_rated
    assert slightly_closer


def test_rides_without_usable_pickup_coordinates_keep_rating_order(app, db, make_driver):
    app.config["DISPATCH_REQUIRE_DRIVER_LOCATION"] = True
    nearby_low = make_driver(km=1, rating=3.0)
    far_high = make_driver(km=30, rating=5.0)
    ride_id = make_ride(db, pickup=(0.0, 0.0))     # (0, 0) means "unknown"
    assert dispatch(app, ride_id) == far_high
    assert nearby_low


def test_assignment_stores_pickup_eta_and_tells_the_driver_how_far_away_it_is(app, db, make_driver):
    app.config["DISPATCH_REQUIRE_DRIVER_LOCATION"] = True
    driver_id = make_driver(km=3)
    ride_id = make_ride(db)
    assert dispatch(app, ride_id) == driver_id
    eta = db.fetchone("SELECT pickup_eta_minutes FROM rides WHERE id = ?", (ride_id,))["pickup_eta_minutes"]
    assert eta and eta >= 1
    note = db.fetchone(
        "SELECT message FROM notifications WHERE user_id = ? AND related_entity_id = ?", (driver_id, ride_id)
    )["message"]
    assert "km from the pickup" in note


def test_required_documents_gate_dispatch(app, db, make_driver):
    app.config["DISPATCH_REQUIRE_DRIVER_LOCATION"] = False
    app.config["DISPATCH_REQUIRED_DOC_TYPES"] = ("DRIVING_PERMIT",)
    try:
        no_docs = make_driver(km=1)
        expired = make_driver(km=1)
        valid = make_driver(km=2)
        for driver_id, expiry in ((expired, "date('now', '-1 day')"), (valid, "date('now', '+90 day')")):
            db.execute(
                f"""INSERT INTO driver_documents (id, driver_id, doc_type, status, expires_at)
                    VALUES (?, ?, 'DRIVING_PERMIT', 'APPROVED', {expiry})""",
                (f"doc_{uuid.uuid4().hex[:8]}", driver_id),
            )
        assert dispatch(app, make_ride(db)) == valid
        assert no_docs and expired
    finally:
        app.config["DISPATCH_REQUIRED_DOC_TYPES"] = ()


# ------------------------------------------------- automatic cancel when nobody comes
def test_unmatched_rides_are_cancelled_after_the_search_timeout(app, db, make_driver):
    app.config["RIDE_SEARCH_TIMEOUT_MINUTES"] = 5
    try:
        old = make_ride(db, minutes_old=6)
        fresh = make_ride(db, minutes_old=1)
        with app.app_context():
            assert RideDispatchService.expire_unmatched_rides() >= 1
        assert db.fetchone("SELECT status FROM rides WHERE id = ?", (old,))["status"] == "CANCELLED"
        assert db.fetchone("SELECT status FROM rides WHERE id = ?", (fresh,))["status"] == "SEARCHING_FOR_DRIVER"
        assert db.fetchone(
            "SELECT COUNT(*) AS c FROM notifications WHERE related_entity_id = ? AND title = 'No driver available'",
            (old,),
        )["c"] == 1
        assert db.fetchone(
            "SELECT COUNT(*) AS c FROM audit_logs WHERE resource_id = ? AND action = 'RIDE_AUTO_CANCELLED_NO_DRIVER'",
            (old,),
        )["c"] == 1
    finally:
        app.config["RIDE_SEARCH_TIMEOUT_MINUTES"] = 0


def test_search_timeout_releases_the_reward_voucher_and_skips_assigned_rides(app, db):
    app.config["RIDE_SEARCH_TIMEOUT_MINUTES"] = 5
    try:
        ride_id = make_ride(db, minutes_old=9)
        db.execute(
            """INSERT INTO rewards_redemptions (id, passenger_id, reward_id, reward_title, points_spent,
                      voucher_code, discount_percent, ride_id, status)
               VALUES (?, 'usr_pass_01', 'rew', 'Test', 0, ?, 10, ?, 'USED')""",
            (f"red_{uuid.uuid4().hex[:6]}", f"V{uuid.uuid4().hex[:8]}", ride_id),
        )
        assigned = make_ride(db, status="DRIVER_ASSIGNED", driver_id="usr_pass_01", minutes_old=30)
        with app.app_context():
            RideDispatchService.expire_unmatched_rides()
        voucher = db.fetchone("SELECT status, ride_id FROM rewards_redemptions WHERE voucher_code LIKE 'V%' AND status = 'ACTIVE' AND ride_id IS NULL")
        assert voucher is not None
        assert db.fetchone("SELECT status FROM rides WHERE id = ?", (assigned,))["status"] == "DRIVER_ASSIGNED"
    finally:
        app.config["RIDE_SEARCH_TIMEOUT_MINUTES"] = 0


# ----------------------------------------------------------- driver location service
def test_location_service_validates_and_stores_positions(app, db, make_driver):
    driver_id = make_driver()
    with app.app_context():
        for bad in ((None, None), (0, 0), (95, 10), ("abc", 1)):
            with pytest.raises(ValueError):
                DriverLocationService.update(driver_id, *bad)
        with pytest.raises(LookupError):
            DriverLocationService.update("usr_missing_driver", 0.31, 32.58)
        assert DriverLocationService.update(driver_id, 0.3201, 32.5902, heading=90, accuracy=12)["ok"]
        stored = DriverLocationService.location_for_driver(driver_id, 60)
        assert (stored["lat"], stored["lng"], stored["heading"]) == (0.3201, 32.5902, 90)
        assert DriverLocationService.update(driver_id, 0.35, 32.6)["throttled"]       # too soon
        assert DriverLocationService.location_for_driver(driver_id, 60)["lat"] == 0.3201
        DriverLocationService.reset()
        assert DriverLocationService.update(driver_id, 0.35, 32.6, accuracy=5000)["ignored"] == "low_accuracy"
        assert DriverLocationService.location_for_driver(driver_id, 60)["lat"] == 0.3201


def test_old_positions_are_not_reported_as_current(app, db, make_driver):
    driver_id = make_driver(km=1, age_seconds=500)
    with app.app_context():
        assert DriverLocationService.location_for_driver(driver_id, 120) is None
        assert DriverLocationService.location_for_driver(driver_id, 900) is not None


def test_position_updates_stream_to_the_passenger_with_an_eta(app, db, make_driver):
    driver_id = make_driver()
    ride_id = make_ride(db, status="DRIVER_ARRIVING", driver_id=driver_id, response="ACCEPTED")
    channel = RealtimeService.subscribe("usr_pass_01")
    with app.app_context():
        result = DriverLocationService.update(driver_id, *at_km(2), heading=45)
    assert result["ride_id"] == ride_id and result["target"] == "pickup"
    assert 1.5 < result["distance_km"] < 2.5 and result["eta_minutes"] >= 1
    event = channel.get_nowait()
    assert event["type"] == "location" and event["ride_id"] == ride_id and event["heading"] == 45
    assert event["target"] == "pickup" and event["eta_minutes"] == result["eta_minutes"]


def test_eta_points_to_the_destination_once_the_trip_has_started(app, db, make_driver):
    driver_id = make_driver()
    make_ride(db, status="TRIP_STARTED", driver_id=driver_id, response="ACCEPTED")
    with app.app_context():
        assert DriverLocationService.update(driver_id, *at_km(1))["target"] == "destination"


def test_route_history_is_recorded_only_during_the_trip_and_is_throttled(app, db, make_driver, monkeypatch):
    monkeypatch.setattr(DriverLocationService, "MIN_INTERVAL_SECONDS", 0)
    arriving = make_driver()
    started = make_driver()
    arriving_ride = make_ride(db, status="DRIVER_ARRIVING", driver_id=arriving, response="ACCEPTED")
    started_ride = make_ride(db, status="TRIP_STARTED", driver_id=started, response="ACCEPTED")
    with app.app_context():
        for _ in range(3):
            DriverLocationService.update(arriving, *at_km(1))
            DriverLocationService.update(started, *at_km(1))
    count = lambda ride: db.fetchone("SELECT COUNT(*) AS c FROM ride_location_points WHERE ride_id = ?", (ride,))["c"]
    assert count(arriving_ride) == 0
    assert count(started_ride) == 1


# --------------------------------------------------------------------- HTTP API
def sign_in(client, user_id, role):
    with client.session_transaction() as browser_session:
        browser_session["user_id"] = user_id
        browser_session["user_role"] = role


XHR = {"X-Requested-With": "RideEasy"}


def test_driver_location_endpoint_requires_driver_role_and_header(client, db, make_driver):
    driver_id = make_driver()
    sign_in(client, "usr_pass_01", "PASSENGER")
    assert client.post("/api/driver/location", json={"lat": 0.3, "lng": 32.5}, headers=XHR).status_code == 403
    sign_in(client, driver_id, "DRIVER")
    assert client.post("/api/driver/location", json={"lat": 0.3, "lng": 32.5}).status_code == 400
    assert client.post("/api/driver/location", json={"lat": 999, "lng": 32.5}, headers=XHR).status_code == 400
    ok = client.post("/api/driver/location", json={"lat": 0.3012, "lng": 32.5012, "accuracy": 8}, headers=XHR)
    assert ok.status_code == 200 and ok.get_json()["ok"] is True
    assert db.fetchone("SELECT current_lat FROM driver_profiles WHERE user_id = ?", (driver_id,))["current_lat"] == 0.3012


def test_ride_status_shows_live_driver_position_and_hides_the_pin_from_the_driver(client, db, make_driver):
    driver_id = make_driver(km=2, age_seconds=3)
    ride_id = make_ride(db, status="DRIVER_ARRIVING", driver_id=driver_id, response="ACCEPTED")
    db.execute("UPDATE rides SET start_pin = '4821' WHERE id = ?", (ride_id,))

    sign_in(client, "usr_pass_01", "PASSENGER")
    ride = client.get(f"/api/ride-status/{ride_id}").get_json()["ride"]
    assert ride["start_pin"] == "4821"
    assert ride["driver_location"]["target"] == "pickup" and ride["driver_location"]["eta_minutes"] >= 1
    assert ride["pickup_lat"] == PICKUP[0]

    sign_in(client, driver_id, "DRIVER")
    driver_view = client.get(f"/api/ride-status/{ride_id}").get_json()["ride"]
    assert "start_pin" not in driver_view


# --------------------------------------------------------------------- realtime
def test_stream_requires_sign_in_and_sends_events(client, app):
    assert client.get("/api/stream").status_code == 302
    sign_in(client, "usr_pass_01", "PASSENGER")
    app.config["REALTIME_STREAM_SECONDS"] = 1
    try:
        response = client.get("/api/stream")
        assert response.status_code == 200
        assert response.mimetype == "text/event-stream"
        assert response.headers["X-Accel-Buffering"] == "no"
        body = response.get_data(as_text=True)
        assert "event: ready" in body and "event: reconnect" in body
    finally:
        app.config["REALTIME_STREAM_SECONDS"] = 55
    assert RealtimeService.stream_count() == 0     # the stream released its slot


def test_stream_reports_busy_when_the_server_is_at_capacity(client, app):
    sign_in(client, "usr_pass_01", "PASSENGER")
    app.config["REALTIME_MAX_STREAMS"] = 0
    try:
        response = client.get("/api/stream")
        assert response.status_code == 503 and response.headers["Retry-After"] == "30"
    finally:
        app.config["REALTIME_MAX_STREAMS"] = 20


def test_realtime_publish_subscribe_and_limits():
    first = RealtimeService.subscribe("u1", max_total=10)
    assert RealtimeService.publish_user("u1", "ride", {"ride_id": "r1"}) == 1
    assert first.get_nowait()["ride_id"] == "r1"
    assert RealtimeService.publish_user("nobody", "ride") == 0

    # a fourth tab replaces the oldest of the user's three streams
    extra = [RealtimeService.subscribe("u1", max_total=10) for _ in range(3)]
    assert first.get_nowait() is None            # told to finish
    assert RealtimeService.stream_count() == 3 and all(extra)

    assert RealtimeService.subscribe("u2", max_total=3) is None     # server capacity reached
    for channel in extra:
        RealtimeService.unsubscribe("u1", channel)
    assert RealtimeService.stream_count() == 0


def test_a_full_queue_keeps_the_newest_event():
    channel = RealtimeService.subscribe("u1")
    for number in range(RealtimeService.QUEUE_SIZE + 5):
        RealtimeService.publish_user("u1", "ride", {"n": number})
    drained = [channel.get_nowait()["n"] for _ in range(channel.qsize())]
    assert drained[-1] == RealtimeService.QUEUE_SIZE + 4 and len(drained) == RealtimeService.QUEUE_SIZE


def test_event_stream_format_and_heartbeat():
    channel = RealtimeService.subscribe("u1")
    RealtimeService.publish_user("u1", "location", {"lat": 1.5})
    stream = RealtimeService.event_stream("u1", channel, max_seconds=1, heartbeat=1)
    chunks = list(stream)
    text = "".join(chunks)
    assert chunks[0].startswith("retry:") and "event: ready" in text
    assert 'event: location\ndata: {"type":"location"' in text and "event: reconnect" in text
    assert RealtimeService.stream_count() == 0


def test_publish_ride_reaches_both_passenger_and_driver(app, db, make_driver):
    driver_id = make_driver()
    ride_id = make_ride(db, status="DRIVER_ARRIVING", driver_id=driver_id, response="ACCEPTED")
    passenger_channel = RealtimeService.subscribe("usr_pass_01")
    driver_channel = RealtimeService.subscribe(driver_id)
    with app.app_context():
        assert RealtimeService.publish_ride(ride_id) == 2
    assert passenger_channel.get_nowait()["ride_id"] == ride_id
    assert driver_channel.get_nowait()["status"] == "DRIVER_ARRIVING"


def test_every_notification_nudges_open_pages(app, db):
    channel = RealtimeService.subscribe("usr_pass_01")
    with app.app_context():
        NotificationService.create_notification(
            "usr_pass_01", "Driver arrived", "Your driver has arrived.", "DRIVER_ASSIGNED", "ride_x1"
        )
    event = channel.get_nowait()
    assert event["type"] == "ride" and event["ride_id"] == "ride_x1" and event["title"] == "Driver arrived"


def test_a_realtime_failure_never_blocks_a_notification(app, db, monkeypatch):
    monkeypatch.setattr(RealtimeService, "publish_user", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with app.app_context():
        notif_id = NotificationService.create_notification("usr_pass_01", "Hello", "World")
    assert db.fetchone("SELECT id FROM notifications WHERE id = ?", (notif_id,)) is not None


# ----------------------------------------------------------------------- web push
def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def vapid_keys():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return b64url(public), b64url(private)


def browser_subscription(endpoint):
    """A subscription like the one a browser creates (real P-256 key and auth secret)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    key = ec.generate_private_key(ec.SECP256R1())
    public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"endpoint": endpoint, "keys": {"p256dh": b64url(public), "auth": b64url(b"0123456789abcdef")}}


@pytest.fixture
def push_server():
    received, status = [], {"code": 201}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            received.append({"headers": dict(self.headers), "body": self.rfile.read(length)})
            self.send_response(status["code"])
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/push", received, status
    server.shutdown()


@pytest.fixture
def push_enabled(app):
    public, private = vapid_keys()
    app.config.update(VAPID_PUBLIC_KEY=public, VAPID_PRIVATE_KEY=private)
    yield public
    app.config.update(VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")


def test_push_is_disabled_without_keys_and_does_nothing(app, db):
    with app.app_context():
        assert PushService.enabled() is False
        PushService.send_to_user("usr_pass_01", "Hi", "There")      # must not raise or query


def test_push_subscription_validation_cap_and_replacement(app, db, push_enabled):
    user = f"usr_push_{uuid.uuid4().hex[:6]}"
    db.execute(
        "INSERT INTO users (id, email, password_hash, role, full_name, phone) VALUES (?, ?, 'x', 'PASSENGER', 'P', '1')",
        (user, f"{user}@rideeasy.test"),
    )
    with app.app_context():
        assert PushService.enabled()
        assert not PushService.save_subscription(user, {"endpoint": "http://insecure.example/x", "keys": {"p256dh": "a", "auth": "b"}})
        assert not PushService.save_subscription(user, {"endpoint": "https://push.example/x", "keys": {}})
        for number in range(7):
            assert PushService.save_subscription(user, browser_subscription(f"https://push.example/{number}"))
        assert db.fetchone("SELECT COUNT(*) AS c FROM push_subscriptions WHERE user_id = ?", (user,))["c"] == 5
        PushService.save_subscription(user, browser_subscription("https://push.example/6"))     # same endpoint: update
        assert db.fetchone("SELECT COUNT(*) AS c FROM push_subscriptions WHERE user_id = ?", (user,))["c"] == 5
        assert PushService.remove_subscription(user, "https://push.example/6") == 1


def test_push_endpoints_need_configuration_header_and_sign_in(client, db, app, push_enabled):
    sub = browser_subscription("https://push.example/endpoint-one")
    assert client.post("/api/push/subscribe", json=sub, headers=XHR).status_code == 302
    sign_in(client, "usr_pass_01", "PASSENGER")
    assert client.post("/api/push/subscribe", json=sub).status_code == 400
    assert client.post("/api/push/subscribe", json=sub, headers=XHR).get_json() == {"success": True}
    assert db.fetchone("SELECT COUNT(*) AS c FROM push_subscriptions WHERE endpoint = ?", (sub["endpoint"],))["c"] == 1
    assert client.post("/api/push/subscribe", json={"endpoint": "x"}, headers=XHR).status_code == 400
    assert client.post("/api/push/unsubscribe", json={"endpoint": sub["endpoint"]}, headers=XHR).status_code == 200
    app.config.update(VAPID_PUBLIC_KEY="", VAPID_PRIVATE_KEY="")
    assert client.post("/api/push/subscribe", json=sub, headers=XHR).status_code == 503


def test_push_message_is_encrypted_signed_and_delivered(app, db, push_enabled, push_server):
    endpoint, received, status = push_server
    with app.app_context():
        PushService._deliver(app, [{"endpoint": endpoint, **browser_subscription(endpoint)["keys"]}],
                             json.dumps({"title": "Driver arrived", "body": "Go outside", "url": "/x"}))
    assert len(received) == 1
    sent = received[0]
    headers = {name.lower(): value for name, value in sent["headers"].items()}
    assert headers["content-encoding"] == "aes128gcm"
    assert headers["authorization"].lower().startswith("vapid ")
    assert "t=" in headers["authorization"] and "k=" in headers["authorization"]
    assert b"Driver arrived" not in sent["body"] and len(sent["body"]) > 40      # encrypted


def test_expired_push_subscriptions_are_removed(app, db, push_enabled, push_server):
    endpoint, received, status = push_server
    status["code"] = 410
    user = f"usr_push_{uuid.uuid4().hex[:6]}"
    db.execute(
        "INSERT INTO users (id, email, password_hash, role, full_name, phone) VALUES (?, ?, 'x', 'PASSENGER', 'P', '1')",
        (user, f"{user}@rideeasy.test"),
    )
    sub = browser_subscription(endpoint)
    db.execute(
        "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth) VALUES (?, ?, ?, ?, ?)",
        (f"push_{uuid.uuid4().hex[:6]}", user, endpoint, sub["keys"]["p256dh"], sub["keys"]["auth"]),
    )
    with app.app_context():
        PushService.send_to_user(user, "Hello", "World", ride_id="r1")
    assert received and db.fetchone("SELECT COUNT(*) AS c FROM push_subscriptions WHERE endpoint = ?", (endpoint,))["c"] == 0


def test_notifications_trigger_a_role_aware_push(app, db, push_enabled, push_server):
    endpoint, received, status = push_server
    with app.app_context():
        driver = db.fetchone("SELECT id FROM users WHERE role = 'DRIVER' LIMIT 1")["id"]
        sub = browser_subscription(endpoint)
        db.execute(
            "INSERT INTO push_subscriptions (id, user_id, endpoint, p256dh, auth) VALUES (?, ?, ?, ?, ?)",
            (f"push_{uuid.uuid4().hex[:6]}", driver, endpoint, sub["keys"]["p256dh"], sub["keys"]["auth"]),
        )
        NotificationService.create_notification(driver, "New trip", "Please respond", "SYSTEM", "ride_zz")
    assert len(received) == 1
    db.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def test_service_worker_is_served_from_the_site_root(client):
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["Content-Type"]
    assert response.headers["Service-Worker-Allowed"] == "/"
    assert b"showNotification" in response.data and b"notificationclick" in response.data


# ------------------------------------------------------------------- end to end
def test_a_complete_trip_from_request_to_completion(app, client, db, make_driver, monkeypatch):
    """Nearest driver is offered the trip, accepts, shares live GPS, the passenger follows the
    ETA, the PIN starts the trip, SOS works mid-trip and the trip completes."""
    from app.services.sms_service import SmsService
    monkeypatch.setattr(SmsService, "send_safety_sms", staticmethod(lambda phone, text: "SENT"))
    app.config["DISPATCH_REQUIRE_DRIVER_LOCATION"] = True
    far, nearest = make_driver(km=8), make_driver(km=1.5)
    ride_id = make_ride(db)
    passenger_events = RealtimeService.subscribe("usr_pass_01")

    # 1. the nearest driver (not the far one) gets the offer
    assert dispatch(app, ride_id) == nearest
    assert db.fetchone("SELECT driver_response_status FROM rides WHERE id = ?", (ride_id,))["driver_response_status"] == "PENDING"

    # 2. the driver sees how far the pickup is, then accepts; the passenger gets a PIN and is nudged
    sign_in(client, nearest, "DRIVER")
    offers = client.get("/driver/api/pending-offers").get_json()["offers"]
    assert offers and 1 <= offers[0]["pickup_distance_km"] <= 2 and offers[0]["pickup_eta_minutes"] >= 1
    assert client.post(f"/driver/rides/{ride_id}/accept").status_code == 302
    pin = db.fetchone("SELECT start_pin FROM rides WHERE id = ?", (ride_id,))["start_pin"]
    assert len(pin) == 4
    kinds = {event["type"] for event in drain(passenger_events)}
    assert "ride" in kinds

    # 3. driving to the pickup: positions stream to the passenger, ETA shrinks as the driver gets closer
    assert client.post(f"/driver/rides/{ride_id}/status", data={"status": "DRIVER_ARRIVING"}).status_code == 302
    etas = []
    for km in (1.5, 0.6):
        DriverLocationService.reset()
        reply = client.post("/api/driver/location", json={"lat": at_km(km)[0], "lng": at_km(km)[1], "heading": 10}, headers=XHR).get_json()
        etas.append(reply["distance_km"])
    assert etas[0] > etas[1]
    locations = [event for event in drain(passenger_events) if event["type"] == "location"]
    assert len(locations) == 2 and locations[-1]["target"] == "pickup"

    sign_in(client, "usr_pass_01", "PASSENGER")
    seen = client.get(f"/api/ride-status/{ride_id}").get_json()["ride"]
    assert seen["start_pin"] == pin and seen["driver_location"]["distance_km"] == etas[1]
    assert "Your trip PIN" in client.get(f"/passenger/rides/{ride_id}").get_data(as_text=True)

    # 4. arrival; the trip cannot start without the PIN
    sign_in(client, nearest, "DRIVER")
    client.post(f"/driver/rides/{ride_id}/status", data={"status": "DRIVER_ARRIVED"})
    wrong = "0000" if pin != "0000" else "1111"
    client.post(f"/driver/rides/{ride_id}/status", data={"status": "TRIP_STARTED", "pin": wrong})
    assert db.fetchone("SELECT status FROM rides WHERE id = ?", (ride_id,))["status"] == "DRIVER_ARRIVED"
    client.post(f"/driver/rides/{ride_id}/status", data={"status": "TRIP_STARTED", "pin": pin})
    assert db.fetchone("SELECT status FROM rides WHERE id = ?", (ride_id,))["status"] == "TRIP_STARTED"

    # 5. mid-trip: ETA now points to the destination, route history is saved, SOS reaches the admins
    DriverLocationService.reset()
    reply = client.post("/api/driver/location", json={"lat": at_km(0.5)[0], "lng": at_km(0.5)[1]}, headers=XHR).get_json()
    assert reply["target"] == "destination"
    assert db.fetchone("SELECT COUNT(*) AS c FROM ride_location_points WHERE ride_id = ?", (ride_id,))["c"] == 1
    sign_in(client, "usr_pass_01", "PASSENGER")
    sos = client.post(f"/trip-safety/rides/{ride_id}/sos", json={"lat": 0.3, "lng": 32.5}, headers=XHR).get_json()
    assert sos["success"] and "/track/" in sos["share_url"]
    assert client.get(sos["share_url"].replace("http://localhost", "")).status_code == 200

    # 6. finish
    sign_in(client, nearest, "DRIVER")
    for status in ("TRIP_COMPLETED", "COMPLETED"):
        client.post(f"/driver/rides/{ride_id}/status", data={"status": status})
    assert db.fetchone("SELECT status FROM rides WHERE id = ?", (ride_id,))["status"] == "COMPLETED"
    assert far


def drain(channel):
    events = []
    while not channel.empty():
        events.append(channel.get_nowait())
    return events
