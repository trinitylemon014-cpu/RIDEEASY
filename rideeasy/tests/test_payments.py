import hashlib
import hmac
import json
import sqlite3
import uuid

import pytest

from app.repositories.database import get_db
from app.services.payment_service import PaymentService


def _create_completed_ride(db, ride_id, passenger_id="usr_pass_01", driver_id="usr_driver_01"):
    db.execute(
        """INSERT INTO rides
           (id, passenger_id, driver_id, category, pickup_address, pickup_lat, pickup_lng,
            destination_address, destination_lat, destination_lng, estimated_distance_km,
            estimated_fare_ugx, final_fare_ugx, payment_method, payment_status, status)
           VALUES (?, ?, ?, 'ECONOMY', 'Kampala', 0.31, 32.58, 'Entebbe', 0.04, 32.44,
                   10, 10000, 10000, 'MTN_MOMO', 'UNPAID', 'COMPLETED')""",
        (ride_id, passenger_id, driver_id)
    )


def test_online_payment_legacy_path_never_claims_paid():
    result = PaymentService.process_payment(10000, "MTN_MOMO", phone="0774339277")
    assert result["success"] is False
    assert result["status"] == "NOT_VERIFIED"


def test_paystack_checkout_creates_pending_payment(client, app, db, monkeypatch):
    client.get("/auth/demo/passenger")
    ride_id = f"ride_pay_{uuid.uuid4().hex[:10]}"
    _create_completed_ride(db, ride_id)
    app.config["PAYSTACK_SECRET_KEY"] = "sk_test_configured"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": True,
                "data": {"authorization_url": "https://checkout.paystack.com/test"}
            }

    checkout_calls = []

    def fake_checkout(*args, **kwargs):
        checkout_calls.append(kwargs["json"]["reference"])
        return FakeResponse()

    monkeypatch.setattr("app.services.payment_service.requests.post", fake_checkout)
    client.get(f"/passenger/rides/{ride_id}")
    with client.session_transaction() as browser_session:
        csrf_token = browser_session["payment_csrf_token"]
    response = client.post(
        f"/payments/paystack/checkout/{ride_id}",
        data={"csrf_token": csrf_token}
    )
    repeated_response = client.post(
        f"/payments/paystack/checkout/{ride_id}",
        data={"csrf_token": csrf_token}
    )

    assert response.status_code == 302
    assert response.headers["Location"] == "https://checkout.paystack.com/test"
    assert repeated_response.status_code == 302
    assert repeated_response.headers["Location"] == response.headers["Location"]
    assert len(checkout_calls) == 1
    payment = db.fetchone("SELECT * FROM payment_transactions WHERE ride_id = ?", (ride_id,))
    assert payment["status"] == "PENDING"
    assert payment["authorization_url"] == response.headers["Location"]
    assert payment["amount_ugx"] == 10000
    assert db.fetchone("SELECT payment_status FROM rides WHERE id = ?", (ride_id,))["payment_status"] == "PENDING"


def test_paystack_checkout_race_reuses_the_active_payment(client, app, db, monkeypatch):
    client.get("/auth/demo/passenger")
    ride_id = f"ride_pay_{uuid.uuid4().hex[:10]}"
    _create_completed_ride(db, ride_id)
    app.config["PAYSTACK_SECRET_KEY"] = "sk_test_configured"
    winner_url = "https://checkout.paystack.com/concurrent-winner"

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": True,
                "data": {"authorization_url": "https://checkout.paystack.com/unpersisted"}
            }

    def fake_checkout(*args, **kwargs):
        db.execute(
            """INSERT INTO payment_transactions
               (id, ride_id, passenger_id, reference, authorization_url, amount_ugx, currency, status)
               VALUES (?, ?, 'usr_pass_01', ?, ?, 10000, 'UGX', 'PENDING')""",
            (f"pay_{uuid.uuid4().hex}", ride_id, f"rideeasy_{uuid.uuid4().hex}", winner_url)
        )
        db.execute(
            "UPDATE rides SET payment_status = 'PENDING' WHERE id = ?",
            (ride_id,)
        )
        return FakeResponse()

    monkeypatch.setattr("app.services.payment_service.requests.post", fake_checkout)
    client.get(f"/passenger/rides/{ride_id}")
    with client.session_transaction() as browser_session:
        csrf_token = browser_session["payment_csrf_token"]
    response = client.post(
        f"/payments/paystack/checkout/{ride_id}",
        data={"csrf_token": csrf_token}
    )

    assert response.status_code == 302
    assert response.headers["Location"] == winner_url
    assert db.fetchone(
        "SELECT COUNT(*) AS count FROM payment_transactions WHERE ride_id = ? AND status IN ('PENDING', 'PAID')",
        (ride_id,)
    )["count"] == 1


def test_verified_payment_is_split_awarded_and_idempotent(app, db):
    ride_id = f"ride_pay_{uuid.uuid4().hex[:10]}"
    _create_completed_ride(db, ride_id)
    payment_id = f"pay_{uuid.uuid4().hex}"
    reference = f"rideeasy_{uuid.uuid4().hex}"
    db.execute(
        """INSERT INTO payment_transactions
           (id, ride_id, passenger_id, reference, amount_ugx, currency, status)
           VALUES (?, ?, 'usr_pass_01', ?, 10000, 'UGX', 'PENDING')""",
        (payment_id, ride_id, reference)
    )
    payment = db.fetchone("SELECT * FROM payment_transactions WHERE id = ?", (payment_id,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            """INSERT INTO payment_transactions
               (id, ride_id, passenger_id, reference, amount_ugx, currency, status)
               VALUES (?, ?, 'usr_pass_01', ?, 10000, 'UGX', 'PENDING')""",
            (f"pay_{uuid.uuid4().hex}", ride_id, f"rideeasy_{uuid.uuid4().hex}")
        )
    verified = {
        "id": 123456,
        "reference": reference,
        "status": "success",
        "amount": 10000,
        "currency": "UGX",
        "metadata": {"ride_id": ride_id, "passenger_id": "usr_pass_01"},
        "customer": {"first_name": "Grace", "last_name": "Namubiru"}
    }

    with app.app_context():
        assert PaymentService.record_verified_payment(payment, verified) is True
        assert PaymentService.record_verified_payment(payment, verified) is False

    ledger = db.fetchall(
        "SELECT recipient_role, amount_ugx FROM payment_ledger WHERE payment_id = ? ORDER BY recipient_role",
        (payment_id,)
    )
    assert [(row["recipient_role"], row["amount_ugx"]) for row in ledger] == [
        ("ADMIN", 2000), ("DRIVER", 8000)
    ]
    assert db.fetchone("SELECT status FROM payment_transactions WHERE id = ?", (payment_id,))["status"] == "PAID"
    assert db.fetchone("SELECT payment_status FROM rides WHERE id = ?", (ride_id,))["payment_status"] == "PAID"
    assert db.fetchone("SELECT points FROM reward_point_awards WHERE ride_id = ?", (ride_id,))["points"] == 100
    assert db.fetchone(
        "SELECT COUNT(*) AS count FROM notifications WHERE related_entity_id = ?",
        (ride_id,)
    )["count"] == 3
    assert db.fetchone("SELECT COUNT(*) AS count FROM sms_messages WHERE payment_id = ?", (payment_id,))["count"] == 3


def test_paystack_webhook_requires_signature_and_verifies_with_provider(client, app, db, monkeypatch):
    ride_id = f"ride_pay_{uuid.uuid4().hex[:10]}"
    _create_completed_ride(db, ride_id)
    payment_id = f"pay_{uuid.uuid4().hex}"
    reference = f"rideeasy_{uuid.uuid4().hex}"
    db.execute(
        """INSERT INTO payment_transactions
           (id, ride_id, passenger_id, reference, amount_ugx, currency, status)
           VALUES (?, ?, 'usr_pass_01', ?, 10000, 'UGX', 'PENDING')""",
        (payment_id, ride_id, reference)
    )
    app.config["PAYSTACK_SECRET_KEY"] = "test-webhook-key"
    event_body = json.dumps({
        "event": "charge.success",
        "data": {"reference": reference, "status": "success", "amount": 10000}
    }).encode()
    verified = {
        "id": 123456, "reference": reference, "status": "success", "amount": 10000,
        "currency": "UGX",
        "metadata": {"ride_id": ride_id, "passenger_id": "usr_pass_01"},
        "customer": {"first_name": "Grace", "last_name": "Namubiru"}
    }
    monkeypatch.setattr(
        PaymentService, "verify_paystack_payment", staticmethod(lambda _reference: verified)
    )

    rejected = client.post(
        "/payments/paystack/webhook", data=event_body,
        headers={"Content-Type": "application/json", "x-paystack-signature": "invalid"}
    )
    assert rejected.status_code == 401
    signature = hmac.new(b"test-webhook-key", event_body, hashlib.sha512).hexdigest()
    accepted = client.post(
        "/payments/paystack/webhook", data=event_body,
        headers={"Content-Type": "application/json", "x-paystack-signature": signature}
    )
    assert accepted.status_code == 200
    assert db.fetchone("SELECT status FROM payment_transactions WHERE id = ?", (payment_id,))["status"] == "PAID"


def test_payment_mismatch_cannot_settle(app, db):
    ride_id = f"ride_pay_{uuid.uuid4().hex[:10]}"
    _create_completed_ride(db, ride_id)
    payment_id = f"pay_{uuid.uuid4().hex}"
    reference = f"rideeasy_{uuid.uuid4().hex}"
    db.execute(
        """INSERT INTO payment_transactions
           (id, ride_id, passenger_id, reference, amount_ugx, currency, status)
           VALUES (?, ?, 'usr_pass_01', ?, 10000, 'UGX', 'PENDING')""",
        (payment_id, ride_id, reference)
    )
    payment = db.fetchone("SELECT * FROM payment_transactions WHERE id = ?", (payment_id,))
    verified = {
        "reference": reference, "status": "success", "amount": 9999, "currency": "UGX",
        "metadata": {"ride_id": ride_id, "passenger_id": "usr_pass_01"}
    }

    with app.app_context():
        try:
            PaymentService.record_verified_payment(payment, verified)
        except ValueError:
            pass
        else:
            raise AssertionError("Mismatched payment amount was accepted.")

    assert db.fetchone("SELECT status FROM payment_transactions WHERE id = ?", (payment_id,))["status"] == "PENDING"
    assert db.fetchone("SELECT COUNT(*) AS count FROM payment_ledger WHERE payment_id = ?", (payment_id,))["count"] == 0


def test_5000_point_voucher_discounts_selected_ride_by_25_percent(client, db, monkeypatch):
    client.get("/auth/demo/passenger")
    monkeypatch.setattr("app.routes.passenger.LocationService.get_route", lambda *args, **kwargs: {
        "start": {"lat": 0.334, "lng": 32.589, "label": "Acacia Mall, Uganda"},
        "destination": {"lat": 0.3195, "lng": 32.5912, "label": "Garden City, Uganda"},
        "distance_km": 4.2,
        "duration_minutes": 18,
    })
    award_ride_id = f"ride_points_{uuid.uuid4().hex[:10]}"
    _create_completed_ride(db, award_ride_id)
    db.execute(
        "INSERT INTO reward_point_awards (ride_id, passenger_id, points) VALUES (?, 'usr_pass_01', 5000)",
        (award_ride_id,)
    )
    response = client.post(
        "/passenger/rewards/redeem",
        data={"reward_id": "rew_25_percent_5000"},
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert response.status_code == 200
    voucher_code = response.get_json()["voucher"]["voucher_code"]
    assert response.get_json()["voucher"]["discount_percent"] == 25

    booking = client.post("/passenger/book-ride", data={
        "pickup_address": "Acacia Mall, Kololo",
        "destination_address": "Garden City Mall",
        "category": "ECONOMY",
        "payment_method": "MTN_MOMO",
        "reward_voucher_code": voucher_code
    }, follow_redirects=True)
    assert booking.status_code == 200
    redeemed = db.fetchone("SELECT status, ride_id FROM rewards_redemptions WHERE voucher_code = ?", (voucher_code,))
    ride = db.fetchone(
        "SELECT id, estimated_fare_ugx, final_fare_ugx FROM rides WHERE id = ?",
        (redeemed["ride_id"],)
    )
    assert ride["estimated_fare_ugx"] - ride["final_fare_ugx"] == ride["estimated_fare_ugx"] // 4
    assert redeemed["status"] == "USED"
    assert redeemed["ride_id"] == ride["id"]


def test_admin_can_edit_payment_references(client, db):
    client.get("/auth/demo/admin")
    page = client.get("/admin/payments")
    assert page.status_code == 200
    with client.session_transaction() as browser_session:
        csrf_token = browser_session["payment_csrf_token"]

    response = client.post("/admin/payments", data={
        "csrf_token": csrf_token,
        "collection_phone": "0774555123",
        "admin_payout_phone": "0708555123",
        "admin_payout_name": "RideEasy Finance"
    })
    assert response.status_code == 302
    settings = {
        row["setting_key"]: row["setting_value"]
        for row in db.fetchall("SELECT setting_key, setting_value FROM payment_settings")
    }
    assert settings["collection_phone"] == "0774555123"
    assert settings["admin_payout_phone"] == "0708555123"
    assert settings["admin_payout_name"] == "RideEasy Finance"


def test_driver_completion_does_not_fake_payment_success(client, db):
    ride_id = f"ride_pay_{uuid.uuid4().hex[:10]}"
    _create_completed_ride(db, ride_id)
    db.execute("UPDATE rides SET status = 'TRIP_STARTED' WHERE id = ?", (ride_id,))
    client.get("/auth/demo/driver")

    client.post(f"/driver/rides/{ride_id}/status", data={"status": "COMPLETED"})
    assert db.fetchone("SELECT status FROM rides WHERE id = ?", (ride_id,))["status"] == "TRIP_STARTED"
    client.post(f"/driver/rides/{ride_id}/status", data={"status": "TRIP_COMPLETED"})
    client.post(f"/driver/rides/{ride_id}/status", data={"status": "COMPLETED"})

    ride = db.fetchone("SELECT status, payment_status FROM rides WHERE id = ?", (ride_id,))
    assert ride["status"] == "COMPLETED"
    assert ride["payment_status"] == "UNPAID"
