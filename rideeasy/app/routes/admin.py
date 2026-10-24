import uuid
import re
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from app.repositories.database import get_db
from app.services.auth_service import login_required, role_required, AuthService
from app.services import driver_profile_service

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

def _valid_payment_csrf():
    token = request.form.get("csrf_token", "")
    expected = session.get("payment_csrf_token", "")
    return bool(token and expected and secrets.compare_digest(token, expected))

@admin_bp.before_request
@login_required
@role_required("ADMIN")
def before_request():
    pass

@admin_bp.route("/dashboard")
def dashboard():
    user = AuthService.get_current_user()
    db = get_db()

    # Core system metrics
    stats = {
        "total_users": db.fetchone("SELECT COUNT(*) as c FROM users")["c"],
        "active_drivers": db.fetchone("SELECT COUNT(*) as c FROM driver_profiles WHERE is_online = 1")["c"],
        "total_rides": db.fetchone("SELECT COUNT(*) as c FROM rides")["c"],
        "pending_schools": db.fetchone("SELECT COUNT(*) as c FROM school_transport_requests WHERE status = 'PENDING'")["c"],
        "pending_flights": db.fetchone("SELECT COUNT(*) as c FROM flight_requests WHERE status = 'SUBMITTED'")["c"],
        "pending_drivers": db.fetchone("SELECT COUNT(*) as c FROM driver_profiles WHERE verification_status = 'PENDING'")["c"]
    }

    recent_rides = db.fetchall(
        """SELECT r.*, p.full_name as passenger_name, p.avatar_url as passenger_avatar_url,
                  d.full_name as driver_name, d.avatar_url as driver_avatar_url
        FROM rides r
        JOIN users p ON r.passenger_id = p.id
        LEFT JOIN users d ON r.driver_id = d.id
        ORDER BY r.created_at DESC LIMIT 5"""
    )

    recent_audit_logs = db.fetchall(
        """SELECT a.*, u.full_name as user_name, u.avatar_url as user_avatar_url, u.role
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC LIMIT 6"""
    )

    return render_template("admin/dashboard.html", user=user, stats=stats, recent_rides=recent_rides, recent_audit_logs=recent_audit_logs)

@admin_bp.route("/users")
def users():
    user = AuthService.get_current_user()
    db = get_db()
    role_filter = request.args.get("role")
    if role_filter:
        users_list = db.fetchall("SELECT * FROM users WHERE role = ? ORDER BY created_at DESC", (role_filter,))
    else:
        users_list = db.fetchall("SELECT * FROM users ORDER BY created_at DESC")
    return render_template("admin/users.html", user=user, users=users_list, role_filter=role_filter)

@admin_bp.route("/drivers")
def drivers():
    user = AuthService.get_current_user()
    db = get_db()
    drivers_list = db.fetchall(
        """SELECT u.*, d.license_number, d.national_id_nin, d.verification_status, d.is_online, d.rating_avg, d.total_trips,
                  d.date_of_birth, d.years_experience,
                  v.id AS vehicle_id, v.plate_number, v.make, v.model, v.year AS vehicle_year, v.color AS vehicle_color,
                  v.capacity AS vehicle_capacity, v.category as vehicle_category,
                  (SELECT COUNT(*) FROM vehicle_photos p WHERE p.vehicle_id = v.id) AS photo_count
        FROM users u
        JOIN driver_profiles d ON d.user_id = u.id
        LEFT JOIN vehicles v ON v.driver_id = u.id
        ORDER BY u.created_at DESC"""
    )
    for row in drivers_list:
        row["age"] = driver_profile_service.age_from_dob(row.get("date_of_birth"))
        row["license_display"] = driver_profile_service.display_value(row.get("license_number")) or "Not provided"
        row["nin_display"] = driver_profile_service.display_value(row.get("national_id_nin")) or "Not provided"
    return render_template("admin/drivers.html", user=user, drivers=drivers_list)

@admin_bp.route("/drivers/<driver_id>/verify", methods=["POST"])
def verify_driver(driver_id):
    action = request.form.get("action", "APPROVED")
    db = get_db()
    db.execute("UPDATE driver_profiles SET verification_status = ? WHERE user_id = ?", (action, driver_id))
    db.execute("UPDATE users SET is_verified = ? WHERE id = ?", (1 if action == "APPROVED" else 0, driver_id))

    user = AuthService.get_current_user()
    db.execute(
        "INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (f"aud_{uuid.uuid4().hex[:8]}", user["id"], f"DRIVER_VERIFICATION_{action}", "DRIVER_PROFILE", driver_id, f"Set to {action}")
    )

    flash(f"Driver status set to {action}.", "info")
    return redirect(url_for("admin.drivers"))

@admin_bp.route("/schools")
def schools():
    user = AuthService.get_current_user()
    db = get_db()
    requests_list = db.fetchall(
        """SELECT r.*, s.school_name, s.contact_person, s.phone as school_phone,
                  u.full_name as assigned_driver_name, u.avatar_url as assigned_driver_avatar_url,
                  v.plate_number as assigned_vehicle_plate
        FROM school_transport_requests r
        JOIN schools s ON r.school_id = s.user_id
        LEFT JOIN users u ON r.assigned_driver_id = u.id
        LEFT JOIN vehicles v ON r.assigned_vehicle_id = v.id
        ORDER BY r.created_at DESC"""
    )
    drivers = db.fetchall(
        """SELECT u.id, u.full_name, v.id as vehicle_id, v.plate_number, v.make, v.model, v.category
        FROM users u
        JOIN driver_profiles d ON d.user_id = u.id
        JOIN vehicles v ON v.driver_id = u.id
        WHERE d.verification_status = 'APPROVED'"""
    )
    return render_template("admin/schools.html", user=user, requests=requests_list, drivers=drivers)

@admin_bp.route("/schools/requests/<request_id>/assign", methods=["POST"])
def assign_school_request(request_id):
    driver_id = request.form.get("driver_id")
    agreed_price = int(request.form.get("agreed_price_ugx", 350000))
    status = request.form.get("status", "VEHICLE_ASSIGNED")

    db = get_db()
    vehicle = db.fetchone("SELECT id FROM vehicles WHERE driver_id = ?", (driver_id,))
    vehicle_id = vehicle["id"] if vehicle else None

    db.execute(
        """UPDATE school_transport_requests 
        SET assigned_driver_id = ?, assigned_vehicle_id = ?, agreed_price_ugx = ?, status = ?, invoice_status = 'INVOICED'
        WHERE id = ?""",
        (driver_id, vehicle_id, agreed_price, status, request_id)
    )

    user = AuthService.get_current_user()
    db.execute(
        "INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (f"aud_{uuid.uuid4().hex[:8]}", user["id"], "ASSIGN_SCHOOL_TRANSPORT", "SCHOOL_REQUEST", request_id, f"Driver: {driver_id}, Price: {agreed_price} UGX")
    )

    flash("School transport request updated with assigned driver and verified vehicle.", "success")
    return redirect(url_for("admin.schools"))

@admin_bp.route("/flights")
def flights():
    user = AuthService.get_current_user()
    db = get_db()
    requests_list = db.fetchall(
        """SELECT r.*, u.full_name as passenger_name, u.avatar_url as passenger_avatar_url,
                  u.phone as passenger_phone, c.company_name as assigned_company_name
        FROM flight_requests r
        JOIN users u ON r.passenger_id = u.id
        LEFT JOIN travel_companies c ON r.assigned_company_id = c.user_id
        ORDER BY r.created_at DESC"""
    )
    partners = db.fetchall("SELECT u.id, c.company_name FROM users u JOIN travel_companies c ON c.user_id = u.id")
    return render_template("admin/flights.html", user=user, requests=requests_list, partners=partners)

@admin_bp.route("/flights/requests/<request_id>/assign", methods=["POST"])
def assign_flight_request(request_id):
    partner_id = request.form.get("travel_company_id")
    db = get_db()
    db.execute(
        "UPDATE flight_requests SET assigned_company_id = ?, status = 'ASSIGNED' WHERE id = ?",
        (partner_id, request_id)
    )

    user = AuthService.get_current_user()
    db.execute(
        "INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (f"aud_{uuid.uuid4().hex[:8]}", user["id"], "ASSIGN_FLIGHT_REQUEST", "FLIGHT_REQUEST", request_id, f"Assigned to partner: {partner_id}")
    )

    flash("Flight inquiry assigned to travel company partner.", "success")
    return redirect(url_for("admin.flights"))

@admin_bp.route("/pricing", methods=["GET", "POST"])
def pricing():
    user = AuthService.get_current_user()
    db = get_db()
    if request.method == "POST":
        category = request.form.get("category")
        base = int(request.form.get("base_fare_ugx", 0))
        per_km = int(request.form.get("per_km_ugx", 0))
        per_min = int(request.form.get("per_min_ugx", 0))
        min_fare = int(request.form.get("min_fare_ugx", 0))

        db.execute(
            """UPDATE pricing_configs 
            SET base_fare_ugx = ?, per_km_ugx = ?, per_min_ugx = ?, min_fare_ugx = ? 
            WHERE category = ?""",
            (base, per_km, per_min, min_fare, category)
        )
        flash(f"Pricing configuration for {category} updated.", "success")
        return redirect(url_for("admin.pricing"))

    configs = db.fetchall("SELECT * FROM pricing_configs")
    return render_template("admin/pricing.html", user=user, configs=configs)

@admin_bp.route("/audit-logs")
def audit_logs():
    user = AuthService.get_current_user()
    db = get_db()
    logs = db.fetchall(
        """SELECT a.*, u.full_name as user_name, u.avatar_url as user_avatar_url,
                  u.email as user_email, u.role
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC LIMIT 50"""
    )
    return render_template("admin/audit_logs.html", user=user, logs=logs)

@admin_bp.route("/payments", methods=["GET", "POST"])
def payments():
    user = AuthService.get_current_user()
    db = get_db()
    if request.method == "POST":
        if not _valid_payment_csrf():
            abort(400)

        collection_phone = request.form.get("collection_phone", "").strip()
        admin_phone = request.form.get("admin_payout_phone", "").strip()
        admin_name = request.form.get("admin_payout_name", "").strip()
        phone_pattern = r"\+?[0-9]{10,15}"
        if not re.fullmatch(phone_pattern, collection_phone) or not re.fullmatch(phone_pattern, admin_phone):
            flash("Enter valid phone numbers using 10–15 digits and an optional leading +.", "error")
            return redirect(url_for("admin.payments"))
        if not admin_name or len(admin_name) > 100:
            flash("Enter a payout account name of 1–100 characters.", "error")
            return redirect(url_for("admin.payments"))

        for key, value in (
            ("collection_phone", collection_phone),
            ("admin_payout_phone", admin_phone),
            ("admin_payout_name", admin_name)
        ):
            db.execute(
                """INSERT INTO payment_settings (setting_key, setting_value, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(setting_key) DO UPDATE SET
                     setting_value = excluded.setting_value, updated_at = CURRENT_TIMESTAMP""",
                (key, value)
            )
        db.execute(
            """INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details)
               VALUES (?, ?, 'UPDATE_PAYMENT_SETTINGS', 'PAYMENT_SETTINGS', NULL, ?)""",
            (f"aud_{uuid.uuid4().hex[:8]}", user["id"], "Updated payment contact and payout destination.")
        )
        flash("Payment contact and admin payout details updated.", "success")
        return redirect(url_for("admin.payments"))

    settings = {
        row["setting_key"]: row["setting_value"]
        for row in db.fetchall("SELECT setting_key, setting_value FROM payment_settings")
    }
    ledger = db.fetchall(
        """SELECT l.*, p.reference, p.amount_ugx AS gross_amount_ugx, p.payer_name,
                  COALESCE(p.paid_at, p.created_at) AS payment_date, r.id AS ride_id,
                  passenger.full_name AS passenger_name, passenger.avatar_url AS passenger_avatar_url,
                  driver.full_name AS driver_name, driver.avatar_url AS driver_avatar_url
           FROM payment_ledger l
           JOIN payment_transactions p ON p.id = l.payment_id
           JOIN rides r ON r.id = p.ride_id
           JOIN users passenger ON passenger.id = p.passenger_id
           LEFT JOIN users driver ON driver.id = r.driver_id
           ORDER BY l.created_at DESC LIMIT 100"""
    )
    totals = db.fetchall(
        """SELECT recipient_role, payout_status, COALESCE(SUM(amount_ugx), 0) AS amount_ugx,
                  COUNT(*) AS entry_count
           FROM payment_ledger GROUP BY recipient_role, payout_status"""
    )
    monthly_totals = db.fetchall(
        """SELECT substr(COALESCE(p.paid_at, p.created_at), 1, 7) AS month, l.recipient_role,
                  COALESCE(SUM(l.amount_ugx), 0) AS amount_ugx, COUNT(*) AS entry_count
           FROM payment_ledger l JOIN payment_transactions p ON p.id = l.payment_id
           WHERE p.status = 'PAID'
           GROUP BY substr(COALESCE(p.paid_at, p.created_at), 1, 7), l.recipient_role
           ORDER BY month DESC LIMIT 24"""
    )
    sms_failures = db.fetchall(
        """SELECT id, payment_id, recipient_phone, message, status, error_message, created_at
           FROM sms_messages WHERE status != 'SENT'
           ORDER BY created_at DESC LIMIT 20"""
    )
    return render_template(
        "admin/payments.html", user=user, settings=settings, ledger=ledger,
        totals=totals, monthly_totals=monthly_totals, sms_failures=sms_failures
    )

@admin_bp.route("/payments/sms/<message_id>/retry", methods=["POST"])
def retry_payment_sms(message_id):
    if not _valid_payment_csrf():
        abort(400)
    message = get_db().fetchone(
        "SELECT * FROM sms_messages WHERE id = ? AND status != 'SENT'",
        (message_id,)
    )
    if not message:
        abort(404)
    from app.services.sms_service import SmsService
    status = SmsService.send_payment_sms(
        message["payment_id"], message["recipient_phone"], message["message"]
    )
    flash(
        "SMS was submitted to the configured provider." if status == "SENT"
        else f"SMS retry was not delivered ({status.lower().replace('_', ' ')}).",
        "success" if status == "SENT" else "error"
    )
    return redirect(url_for("admin.payments"))

@admin_bp.route("/payments/ledger/<entry_id>/mark-paid", methods=["POST"])
def mark_ledger_entry_paid(entry_id):
    if not _valid_payment_csrf():
        abort(400)
    if request.form.get("confirm_payout") != "yes":
        abort(400)
    db = get_db()
    entry = db.fetchone(
        "SELECT * FROM payment_ledger WHERE id = ? AND payout_status = 'PENDING'",
        (entry_id,)
    )
    if not entry:
        abort(404)

    changed = db.execute(
        """UPDATE payment_ledger SET payout_status = 'PAID', paid_at = CURRENT_TIMESTAMP
           WHERE id = ? AND payout_status = 'PENDING'""",
        (entry_id,)
    )
    if changed:
        user = AuthService.get_current_user()
        db.execute(
            """INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details)
               VALUES (?, ?, 'MARK_MANUAL_PAYOUT_PAID', 'PAYMENT_LEDGER', ?, ?)""",
            (f"aud_{uuid.uuid4().hex[:8]}", user["id"], entry_id,
             f"Marked UGX {entry['amount_ugx']} paid to {entry['recipient_phone']}.")
        )
        from app.services.notification_service import NotificationService
        NotificationService.create_notification(
            entry["recipient_id"],
            "Payout recorded",
            f"An admin recorded your manual payout of UGX {entry['amount_ugx']:,}.",
            related_entity_id=entry_id
        )
        flash("Payout marked paid and recorded in the audit log.", "success")
    return redirect(url_for("admin.payments"))
