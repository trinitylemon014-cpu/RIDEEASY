import hashlib
import hmac
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests
from flask import current_app, url_for

class PaymentService:
    """
    Modular payment gateway abstraction supporting:
    - MTN Mobile Money (MoMo)
    - Airtel Money
    - Card (Visa / Mastercard via authorized acquirer)
    - Cash on Delivery
    """

    SUPPORTED_METHODS = {
        "CASH": "Cash to Driver",
        "MTN_MOMO": "MTN Mobile Money",
        "AIRTEL_MONEY": "Airtel Money",
        "CARD": "Debit / Credit Card",
        "PAYSTACK": "Paystack (Mobile Money / Card)"
    }

    @staticmethod
    def process_payment(amount_ugx: int, method: str, phone: Optional[str] = None, ride_id: Optional[str] = None) -> Dict[str, Any]:
        """Legacy interface: never report an unverified electronic payment as paid."""
        method = method.upper() if method else "CASH"
        txn_ref = f"TXN-{method[:3]}-{uuid.uuid4().hex[:8].upper()}"
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if method == "CASH":
            return {
                "success": True,
                "reference": txn_ref,
                "status": "PENDING_CASH",
                "message": "Pay exact fare in cash directly to your verified driver at trip completion.",
                "amount": amount_ugx,
                "currency": "UGX",
                "timestamp": now_str
            }

        elif method in ("MTN_MOMO", "AIRTEL_MONEY", "CARD", "PAYSTACK"):
            return {
                "success": False,
                "reference": txn_ref,
                "status": "NOT_VERIFIED",
                "message": "Electronic payments must be completed and verified through Paystack.",
                "amount": amount_ugx,
                "currency": "UGX",
                "timestamp": now_str
            }

        return {
            "success": False,
            "reference": txn_ref,
            "status": "FAILED",
            "message": f"Unsupported payment method: {method}",
            "amount": amount_ugx,
            "currency": "UGX",
            "timestamp": now_str
        }

    @staticmethod
    def initialize_paystack_payment(ride: dict, passenger: dict) -> Dict[str, Any]:
        """Create a Paystack checkout and persist its unique, pending reference."""
        secret_key = current_app.config.get("PAYSTACK_SECRET_KEY", "")
        if not secret_key:
            raise RuntimeError("Paystack is not configured. Set PAYSTACK_SECRET_KEY.")
        if not passenger.get("email"):
            raise ValueError("A valid passenger email is required for Paystack checkout.")
        configured_callback = current_app.config.get("PAYSTACK_CALLBACK_URL", "")
        if current_app.config.get("FLASK_ENV") == "production" and not configured_callback:
            raise RuntimeError("Set PAYSTACK_CALLBACK_URL to the HTTPS callback URL before accepting payments.")

        amount_ugx = int(ride.get("final_fare_ugx") or ride.get("estimated_fare_ugx") or 0)
        multiplier = int(current_app.config.get("PAYSTACK_AMOUNT_MULTIPLIER", 1))
        currency = current_app.config.get("PAYSTACK_CURRENCY", "UGX").upper()
        if amount_ugx <= 0 or multiplier <= 0:
            raise ValueError("Payment amount or configured currency multiplier is invalid.")
        from app.repositories.database import get_db
        db = get_db()
        if not db.supports_transactions:
            raise RuntimeError("Paystack payments require a transactional libsql:// or local SQLite database.")
        active_payment = db.fetchone(
            """SELECT * FROM payment_transactions
               WHERE ride_id = ? AND status IN ('PENDING', 'PAID')
               ORDER BY created_at DESC LIMIT 1""",
            (ride["id"],)
        )
        if active_payment and active_payment["status"] == "PAID":
            raise ValueError("This ride has already been paid.")
        if active_payment and active_payment["authorization_url"]:
            return {
                "payment_id": active_payment["id"],
                "reference": active_payment["reference"],
                "authorization_url": active_payment["authorization_url"]
            }
        if active_payment:
            prior_result = PaymentService.verify_paystack_payment(active_payment["reference"])
            if prior_result.get("status") == "success":
                PaymentService.record_verified_payment(active_payment, prior_result)
                raise ValueError("This ride has already been paid.")
            if prior_result.get("status") != "failed":
                raise RuntimeError("An earlier payment attempt is still being confirmed.")
            PaymentService._mark_payment_failed(active_payment)

        reference = f"rideeasy_{uuid.uuid4().hex}"
        callback_url = configured_callback or url_for("payments.paystack_callback", _external=True)
        callback = urlparse(callback_url)
        if (
            not callback.hostname
            or (
                callback.scheme != "https"
                and current_app.config.get("FLASK_ENV") == "production"
            )
        ):
            raise RuntimeError("Paystack callback URL must be a valid HTTPS URL in production.")
        payload = {
            "email": passenger["email"],
            "amount": amount_ugx * multiplier,
            "currency": currency,
            "reference": reference,
            "callback_url": callback_url,
            "channels": ["mobile_money", "card"],
            "metadata": {
                "ride_id": ride["id"],
                "passenger_id": passenger["id"],
                "phone": passenger.get("phone", "")
            }
        }
        response = requests.post(
            "https://api.paystack.co/transaction/initialize",
            json=payload,
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=(3.05, 10)
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("data"), dict):
            raise RuntimeError("Paystack returned an invalid checkout response.")
        authorization_url = result.get("data", {}).get("authorization_url")
        parsed_url = urlparse(authorization_url or "")
        if (
            not result.get("status")
            or parsed_url.scheme != "https"
            or not parsed_url.hostname
            or not parsed_url.hostname.endswith(".paystack.com")
        ):
            raise RuntimeError("Paystack did not return a valid checkout URL.")

        payment_id = f"pay_{uuid.uuid4().hex}"
        try:
            db.execute_transaction([
                (
                    """INSERT INTO payment_transactions
                       (id, ride_id, passenger_id, reference, authorization_url, amount_ugx, currency, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
                    (payment_id, ride["id"], passenger["id"], reference, authorization_url, amount_ugx, currency)
                ),
                (
                    """UPDATE rides SET payment_status = 'PENDING', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ? AND passenger_id = ? AND status = 'COMPLETED'
                         AND payment_status != 'PAID'""",
                    (ride["id"], passenger["id"]), 1
                )
            ])
        except Exception as exc:
            current_payment = db.fetchone(
                """SELECT * FROM payment_transactions
                   WHERE ride_id = ? AND status IN ('PENDING', 'PAID')
                   ORDER BY created_at DESC LIMIT 1""",
                (ride["id"],)
            )
            if current_payment and current_payment["status"] == "PAID":
                raise ValueError("This ride has already been paid.") from exc
            if current_payment and current_payment["authorization_url"]:
                return {
                    "payment_id": current_payment["id"],
                    "reference": current_payment["reference"],
                    "authorization_url": current_payment["authorization_url"]
                }
            if current_payment:
                raise RuntimeError("Another payment attempt is already being initialized.") from exc
            raise
        return {
            "payment_id": payment_id,
            "reference": reference,
            "authorization_url": authorization_url
        }

    @staticmethod
    def _mark_payment_failed(payment: dict) -> None:
        from app.repositories.database import get_db
        db = get_db()
        db.execute(
            """UPDATE payment_transactions SET status = 'FAILED', updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND status = 'PENDING'""",
            (payment["id"],)
        )
        db.execute(
            """UPDATE rides SET payment_status = 'UNPAID', updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND payment_status = 'PENDING'
                 AND NOT EXISTS (
                   SELECT 1 FROM payment_transactions
                   WHERE ride_id = ? AND status = 'PENDING'
                 )""",
            (payment["ride_id"], payment["ride_id"])
        )

    @staticmethod
    def verify_paystack_payment(reference: str) -> Dict[str, Any]:
        """Verify a reference directly with Paystack; callbacks alone are not trusted."""
        secret_key = current_app.config.get("PAYSTACK_SECRET_KEY", "")
        if not secret_key:
            raise RuntimeError("Paystack is not configured. Set PAYSTACK_SECRET_KEY.")
        response = requests.get(
            "https://api.paystack.co/transaction/verify",
            params={"reference": reference},
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=(3.05, 10)
        )
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not result.get("status") or not isinstance(result.get("data"), dict):
            raise RuntimeError("Paystack returned an invalid verification response.")
        return result["data"]

    @staticmethod
    def verify_webhook_signature(raw_body: bytes, signature: Optional[str]) -> bool:
        secret_key = current_app.config.get("PAYSTACK_SECRET_KEY", "")
        if not secret_key or not signature:
            return False
        expected = hmac.new(secret_key.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()
        return hmac.compare_digest(expected, signature)

    @staticmethod
    def record_verified_payment(payment: dict, verified: dict) -> bool:
        """Atomically settle a verified, completed ride once and create its ledger shares."""
        if verified.get("status") != "success":
            return False

        from app.repositories.database import get_db
        db = get_db()
        if not db.supports_transactions:
            raise RuntimeError("Payment settlement requires a transactional libsql:// or local SQLite database.")
        multiplier = int(current_app.config.get("PAYSTACK_AMOUNT_MULTIPLIER", 1))
        metadata = verified.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("Verified Paystack metadata is invalid.")
        try:
            verified_amount = int(verified.get("amount", -1))
        except (TypeError, ValueError):
            raise ValueError("Verified Paystack amount is invalid.") from None
        verified_currency = verified.get("currency")
        if not isinstance(verified_currency, str):
            raise ValueError("Verified Paystack currency is invalid.")
        expected_amount = int(payment["amount_ugx"]) * multiplier
        if (
            verified_amount != expected_amount
            or verified.get("reference") != payment["reference"]
            or verified_currency.upper() != payment["currency"].upper()
            or (metadata.get("ride_id") and metadata["ride_id"] != payment["ride_id"])
            or (metadata.get("passenger_id") and metadata["passenger_id"] != payment["passenger_id"])
        ):
            raise ValueError("Verified Paystack amount, currency, or ride metadata does not match.")

        context = db.fetchone(
            """SELECT p.status AS payment_status, p.ride_id, p.passenger_id, p.amount_ugx,
                      r.status AS ride_status, r.payment_status AS ride_payment_status, r.driver_id,
                      passenger.full_name AS passenger_name,
                      driver.full_name AS driver_name, driver.phone AS driver_phone,
                      admin.id AS admin_id,
                      COALESCE(admin_name.setting_value, admin.full_name) AS admin_name,
                      admin_phone.setting_value AS admin_phone
               FROM payment_transactions p
               JOIN rides r ON r.id = p.ride_id
               JOIN users passenger ON passenger.id = p.passenger_id
               LEFT JOIN users driver ON driver.id = r.driver_id
               LEFT JOIN users admin ON admin.role = 'ADMIN'
               LEFT JOIN payment_settings admin_phone ON admin_phone.setting_key = 'admin_payout_phone'
               LEFT JOIN payment_settings admin_name ON admin_name.setting_key = 'admin_payout_name'
               WHERE p.id = ? LIMIT 1""",
            (payment["id"],)
        )
        if not context:
            raise ValueError("Payment or associated ride could not be found.")
        if context["payment_status"] == "PAID":
            return False
        if context["ride_payment_status"] == "PAID":
            raise ValueError("This ride has already been settled by another payment.")
        if context["payment_status"] != "PENDING" or context["ride_status"] != "COMPLETED":
            raise ValueError("Only a pending payment for a completed ride can be settled.")
        if not context["driver_id"] or not context["driver_phone"] or not context["admin_id"]:
            raise ValueError("A verified driver and admin payout account are required.")

        amount = int(context["amount_ugx"])
        admin_share = amount * 20 // 100
        driver_share = amount - admin_share
        customer = verified.get("customer") or {}
        if not isinstance(customer, dict):
            customer = {}
        payer_name = " ".join(
            part.strip() for part in (customer.get("first_name"), customer.get("last_name"))
            if isinstance(part, str) and part.strip()
        )[:140] or customer.get("account_name") or verified.get("account_name") or context["passenger_name"]
        reference = payment["reference"]
        payment_id = payment["id"]
        ride_id = context["ride_id"]
        passenger_id = context["passenger_id"]
        admin_message = (
            f"Verified UGX {amount:,} payment from {payer_name or 'a passenger'} for ride "
            f"{ride_id}. Driver: {context['driver_name']}. Admin share: UGX {admin_share:,}."
        )
        driver_message = f"Ride {ride_id} payment verified. Your 80% share is UGX {driver_share:,}."
        passenger_message = f"Payment verified for ride {ride_id}. You earned 100 RideEasy points."

        operations = [
            (
                """INSERT OR IGNORE INTO payment_ledger
                   (id, payment_id, recipient_id, recipient_role, recipient_name, recipient_phone, amount_ugx)
                   SELECT ?, ?, ?, 'ADMIN', ?, ?, ?
                   WHERE EXISTS (SELECT 1 FROM payment_transactions WHERE id = ? AND status = 'PENDING')""",
                (f"led_{uuid.uuid4().hex}", payment_id, context["admin_id"], context["admin_name"],
                 context["admin_phone"] or "", admin_share, payment_id)
            ),
            (
                """INSERT OR IGNORE INTO payment_ledger
                   (id, payment_id, recipient_id, recipient_role, recipient_name, recipient_phone, amount_ugx)
                   SELECT ?, ?, ?, 'DRIVER', ?, ?, ?
                   WHERE EXISTS (SELECT 1 FROM payment_transactions WHERE id = ? AND status = 'PENDING')""",
                (f"led_{uuid.uuid4().hex}", payment_id, context["driver_id"], context["driver_name"],
                 context["driver_phone"], driver_share, payment_id)
            ),
            (
                """INSERT OR IGNORE INTO reward_point_awards (ride_id, passenger_id, points)
                   SELECT ?, ?, 100
                   WHERE EXISTS (SELECT 1 FROM payment_transactions WHERE id = ? AND status = 'PENDING')""",
                (ride_id, passenger_id, payment_id)
            ),
            (
                """INSERT INTO notifications (id, user_id, title, message, type, is_read, related_entity_id)
                   SELECT ?, ?, 'Payment received', ?, 'SYSTEM', 0, ?
                   WHERE EXISTS (SELECT 1 FROM payment_transactions WHERE id = ? AND status = 'PENDING')
                     AND NOT EXISTS (SELECT 1 FROM notifications WHERE user_id = ? AND related_entity_id = ? AND title = 'Payment received')""",
                (f"notif_{uuid.uuid4().hex}", context["admin_id"], admin_message, ride_id,
                 payment_id, context["admin_id"], ride_id)
            ),
            (
                """INSERT INTO notifications (id, user_id, title, message, type, is_read, related_entity_id)
                   SELECT ?, ?, 'Ride earnings updated', ?, 'SYSTEM', 0, ?
                   WHERE EXISTS (SELECT 1 FROM payment_transactions WHERE id = ? AND status = 'PENDING')
                     AND NOT EXISTS (SELECT 1 FROM notifications WHERE user_id = ? AND related_entity_id = ? AND title = 'Ride earnings updated')""",
                (f"notif_{uuid.uuid4().hex}", context["driver_id"], driver_message, ride_id,
                 payment_id, context["driver_id"], ride_id)
            ),
            (
                """INSERT INTO notifications (id, user_id, title, message, type, is_read, related_entity_id)
                   SELECT ?, ?, 'Payment verified', ?, 'SYSTEM', 0, ?
                   WHERE EXISTS (SELECT 1 FROM payment_transactions WHERE id = ? AND status = 'PENDING')
                     AND NOT EXISTS (SELECT 1 FROM notifications WHERE user_id = ? AND related_entity_id = ? AND title = 'Payment verified')""",
                (f"notif_{uuid.uuid4().hex}", passenger_id, passenger_message, ride_id,
                 payment_id, passenger_id, ride_id)
            ),
            (
                """UPDATE rides SET payment_status = 'PAID', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'COMPLETED' AND payment_status != 'PAID'
                     AND EXISTS (SELECT 1 FROM payment_transactions WHERE id = ? AND status = 'PENDING')""",
                (ride_id, payment_id), 1
            ),
            (
                """UPDATE payment_transactions
                   SET status = 'PAID', payer_name = ?, provider_reference = ?,
                       paid_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND status = 'PENDING'""",
                (payer_name, str(verified.get("id", "")), payment_id), 1
            )
        ]
        rowcounts = db.execute_transaction(operations)
        if rowcounts[-1] == 0:
            return False

        from app.services.sms_service import SmsService
        passenger = db.fetchone("SELECT phone FROM users WHERE id = ?", (passenger_id,))
        for phone, message in (
            (context["admin_phone"], admin_message),
            (context["driver_phone"], driver_message),
            ((passenger or {}).get("phone"), passenger_message)
        ):
            if phone:
                SmsService.send_payment_sms(payment_id, phone, message)
        return True

    @staticmethod
    def generate_receipt_data(ride: dict, passenger: dict, driver: Optional[dict] = None) -> Dict[str, Any]:
        """Generates itemized receipt data for completed trips."""
        fare = ride.get("final_fare_ugx") or ride.get("estimated_fare_ugx") or 0
        base_fare = int(fare * 0.35)
        distance_fare = int(fare * 0.55)
        tax = fare - (base_fare + distance_fare)

        return {
            "receipt_number": f"REC-UG-{ride['id'][:8].upper()}",
            "date": ride.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            "passenger_name": passenger.get("full_name", "Passenger"),
            "driver_name": driver.get("full_name", "Verified RideEasy Driver") if driver else "Assigned Driver",
            "vehicle_plate": driver.get("plate_number", "UBD 204K") if driver else "UBD 204K",
            "pickup": ride.get("pickup_address", ""),
            "destination": ride.get("destination_address", ""),
            "distance_km": ride.get("estimated_distance_km", 0),
            "category": ride.get("category", "ECONOMY"),
            "payment_method": PaymentService.SUPPORTED_METHODS.get(ride.get("payment_method", "CASH"), "Cash"),
            "status": ride.get("payment_status", "PAID"),
            "fare_breakdown": {
                "base_fare": base_fare,
                "distance_fare": distance_fare,
                "service_fee": tax,
                "total_ugx": fare
            }
        }
