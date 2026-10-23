import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from app.repositories.database import get_db
from app.services.auth_service import login_required, role_required, AuthService

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

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
        """SELECT r.*, p.full_name as passenger_name, d.full_name as driver_name
        FROM rides r
        JOIN users p ON r.passenger_id = p.id
        LEFT JOIN users d ON r.driver_id = d.id
        ORDER BY r.created_at DESC LIMIT 5"""
    )

    recent_audit_logs = db.fetchall(
        """SELECT a.*, u.full_name as user_name, u.role
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
                  v.plate_number, v.make, v.model, v.category as vehicle_category
        FROM users u
        JOIN driver_profiles d ON d.user_id = u.id
        LEFT JOIN vehicles v ON v.driver_id = u.id
        ORDER BY u.created_at DESC"""
    )
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
                  u.full_name as assigned_driver_name, v.plate_number as assigned_vehicle_plate
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
        """SELECT r.*, u.full_name as passenger_name, u.phone as passenger_phone, c.company_name as assigned_company_name
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
        """SELECT a.*, u.full_name as user_name, u.email as user_email, u.role
        FROM audit_logs a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.created_at DESC LIMIT 50"""
    )
    return render_template("admin/audit_logs.html", user=user, logs=logs)
