import secrets

import requests
from flask import Blueprint, abort, current_app, flash, redirect, request, session, url_for
from werkzeug.exceptions import BadRequest

from app.repositories.database import get_db
from app.services.auth_service import AuthService, login_required, role_required
from app.services.payment_service import PaymentService

payments_bp = Blueprint("payments", __name__, url_prefix="/payments")


def _check_csrf():
    token = request.form.get("csrf_token", "")
    expected = session.get("payment_csrf_token", "")
    return bool(token and expected and secrets.compare_digest(token, expected))


@payments_bp.route("/paystack/checkout/<ride_id>", methods=["POST"])
@login_required
@role_required("PASSENGER")
def start_paystack_checkout(ride_id):
    user = AuthService.get_current_user()
    if not _check_csrf():
        abort(400, "Invalid payment form token.")

    db = get_db()
    ride = db.fetchone(
        "SELECT * FROM rides WHERE id = ? AND passenger_id = ?",
        (ride_id, user["id"])
    )
    if not ride:
        abort(404)
    if ride["status"] != "COMPLETED":
        flash("Payment is available after your driver completes the ride.", "error")
        return redirect(url_for("passenger.ride_detail", ride_id=ride_id))
    if ride["payment_status"] == "PAID":
        flash("This ride has already been paid.", "info")
        return redirect(url_for("passenger.ride_detail", ride_id=ride_id))

    try:
        checkout = PaymentService.initialize_paystack_payment(ride, user)
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        current_app.logger.error("Unable to initialize Paystack checkout for ride %s: %s", ride_id, exc)
        flash("Online payment could not be started. Please try again or contact support.", "error")
        return redirect(url_for("passenger.ride_detail", ride_id=ride_id))
    return redirect(checkout["authorization_url"])


@payments_bp.route("/paystack/callback", methods=["GET"])
def paystack_callback():
    reference = request.args.get("reference", "").strip()
    if not reference or len(reference) > 100:
        abort(400)

    db = get_db()
    payment = db.fetchone("SELECT * FROM payment_transactions WHERE reference = ?", (reference,))
    if not payment:
        abort(404)
    try:
        verified = PaymentService.verify_paystack_payment(reference)
        if verified.get("reference") != reference:
            abort(400)
        if verified.get("status") == "success":
            PaymentService.record_verified_payment(payment, verified)
        elif verified.get("status") == "failed":
            _record_failed_payment(payment)
        else:
            flash("Payment is still awaiting Paystack confirmation. We will update your ride when verified.", "info")
    except requests.RequestException as exc:
        current_app.logger.error("Paystack verification temporarily failed for %s: %s", reference, exc)
        flash("Payment verification is still processing. Check your ride again shortly.", "info")
    except RuntimeError as exc:
        current_app.logger.error("Paystack verification is not available: %s", exc)
        flash("Payment verification is unavailable. Please contact support.", "error")
    except ValueError as exc:
        current_app.logger.error("Paystack verification did not match payment %s: %s", reference, exc)
        abort(400)

    return redirect(url_for("passenger.ride_detail", ride_id=payment["ride_id"]))


@payments_bp.route("/paystack/webhook", methods=["POST"])
def paystack_webhook():
    raw_body = request.get_data(cache=True)
    if not PaymentService.verify_webhook_signature(
        raw_body, request.headers.get("x-paystack-signature")
    ):
        abort(401)
    try:
        event = request.get_json(force=True)
    except BadRequest:
        abort(400)

    if not isinstance(event, dict) or event.get("event") != "charge.success":
        return "", 200
    data = event.get("data")
    reference = data.get("reference") if isinstance(data, dict) else None
    if not isinstance(reference, str) or not reference or len(reference) > 100:
        abort(400)

    db = get_db()
    payment = db.fetchone("SELECT * FROM payment_transactions WHERE reference = ?", (reference,))
    if not payment:
        return "", 200
    try:
        verified = PaymentService.verify_paystack_payment(reference)
        if verified.get("reference") != reference:
            abort(400)
        if verified.get("status") == "success":
            PaymentService.record_verified_payment(payment, verified)
        elif verified.get("status") == "failed":
            _record_failed_payment(payment)
        else:
            return "Payment is not yet confirmed", 503
    except requests.RequestException as exc:
        current_app.logger.error("Paystack webhook verification failed for %s: %s", reference, exc)
        return "Verification temporarily unavailable", 503
    except RuntimeError as exc:
        current_app.logger.error("Paystack webhook could not verify %s: %s", reference, exc)
        return "Verification temporarily unavailable", 503
    except ValueError as exc:
        current_app.logger.error("Paystack webhook verification mismatch for %s: %s", reference, exc)
        abort(400)
    return "", 200


def _record_failed_payment(payment):
    db = get_db()
    db.execute(
        """UPDATE payment_transactions SET status = 'FAILED', updated_at = CURRENT_TIMESTAMP
           WHERE id = ? AND status = 'PENDING'""",
        (payment["id"],)
    )
    pending = db.fetchone(
        "SELECT COUNT(*) AS total FROM payment_transactions WHERE ride_id = ? AND status = 'PENDING'",
        (payment["ride_id"],)
    )
    if not pending or pending["total"] == 0:
        db.execute(
            """UPDATE rides SET payment_status = 'UNPAID', updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND payment_status = 'PENDING'""",
            (payment["ride_id"],)
        )
