import secrets
import uuid
from datetime import date, datetime, timedelta
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session, abort, jsonify
from app.repositories.database import get_db
from app.services.auth_service import login_required, role_required, AuthService
from app.services.ride_dispatch_service import RideDispatchService
from app.services.notification_service import NotificationService
from app.services.vehicle_photo_service import VehiclePhotoService
from app.services import driver_profile_service as profile_rules

driver_bp = Blueprint("driver", __name__, url_prefix="/driver")

@driver_bp.before_request
@login_required
@role_required("DRIVER", "ADMIN")
def before_request():
    pass

def _csrf_ok():
    token = request.form.get("csrf_token", "")
    expected = session.get("payment_csrf_token", "")
    return bool(token and expected and secrets.compare_digest(token, expected))

def get_driver_earnings_summary(driver_id, db):
    """
    Computes real-time daily earnings and operational stats over the past 7 days
    (from 6 days ago up to today, inclusive) for the Driver Dashboard chart and metrics.
    """
    now = datetime.now()
    days_data = []
    date_map = {}

    for i in range(6, -1, -1):
        d = now - timedelta(days=i)
        d_str = d.strftime("%Y-%m-%d")
        item = {
            "date": d_str,
            "day_name": d.strftime("%a"),               # Mon, Tue, etc.
            "label": d.strftime("%a, %b %d"),           # Mon, Oct 19
            "short_label": d.strftime("%b %d"),         # Oct 19
            "is_today": (i == 0),
            "earnings_ugx": 0,
            "trip_count": 0,
            "trips": []
        }
        days_data.append(item)
        date_map[d_str] = item

    earliest_date = (now - timedelta(days=6)).strftime("%Y-%m-%d 00:00:00")
    rides = db.fetchall(
        """SELECT r.id, r.pickup_address, r.destination_address, r.category,
                  r.estimated_fare_ugx, r.final_fare_ugx, r.payment_method,
                  COALESCE(p.paid_at, p.created_at) AS created_at,
                  date(COALESCE(p.paid_at, p.created_at)) as trip_date,
                  l.amount_ugx as driver_share_ugx, u.full_name as passenger_name
        FROM payment_ledger l
        JOIN payment_transactions p ON p.id = l.payment_id
        JOIN rides r ON r.id = p.ride_id
        JOIN users u ON u.id = r.passenger_id
        WHERE l.recipient_id = ? AND l.recipient_role = 'DRIVER'
          AND p.status = 'PAID' AND COALESCE(p.paid_at, p.created_at) >= ?
        ORDER BY COALESCE(p.paid_at, p.created_at) ASC""",
        (driver_id, earliest_date)
    )

    for r in rides:
        trip_date = r["trip_date"]
        fare = r["driver_share_ugx"]
        if trip_date in date_map:
            date_map[trip_date]["earnings_ugx"] += fare
            date_map[trip_date]["trip_count"] += 1
            date_map[trip_date]["trips"].append({
                "id": r["id"],
                "passenger": r["passenger_name"],
                "route": f"{r['pickup_address']} → {r['destination_address']}",
                "fare_ugx": fare,
                "category": r["category"],
                "payment_method": r["payment_method"],
                "time": r["created_at"][11:16] if len(r["created_at"]) >= 16 else ""
            })

    total_week_earnings = sum(d["earnings_ugx"] for d in days_data)
    total_week_trips = sum(d["trip_count"] for d in days_data)
    today_earnings = days_data[-1]["earnings_ugx"] if days_data else 0
    today_trips = days_data[-1]["trip_count"] if days_data else 0
    avg_daily_earnings = round(total_week_earnings / 7)

    max_day = max(days_data, key=lambda x: x["earnings_ugx"]) if days_data else None
    max_day_earnings = max_day["earnings_ugx"] if max_day else 0
    max_day_label = max_day["label"] if max_day and max_day["earnings_ugx"] > 0 else "N/A"

    return {
        "days": days_data,
        "total_week_earnings": total_week_earnings,
        "total_week_trips": total_week_trips,
        "today_earnings": today_earnings,
        "today_trips": today_trips,
        "avg_daily_earnings": avg_daily_earnings,
        "max_day_earnings": max_day_earnings,
        "max_day_label": max_day_label,
        "period_start": days_data[0]["label"],
        "period_end": days_data[-1]["label"]
    }

@driver_bp.route("/dashboard")
def dashboard():
    user = AuthService.get_current_user()
    db = get_db()

    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    vehicle = db.fetchone("SELECT * FROM vehicles WHERE driver_id = ?", (user["id"],))

    total_earnings = db.fetchone(
        """SELECT COALESCE(SUM(amount_ugx), 0) as total
        FROM payment_ledger WHERE recipient_id = ? AND recipient_role = 'DRIVER'""",
        (user["id"],)
    )

    earnings_summary = get_driver_earnings_summary(user["id"], db)
    photo_count = VehiclePhotoService.count_photos(vehicle["id"]) if vehicle else 0
    completion = profile_rules.completeness(profile, vehicle, photo_count)
    pending_rides = []
    active_ride = None
    if profile and profile["is_online"] and profile["verification_status"] == "APPROVED":
        pending_rides = db.fetchall(
            """SELECT r.*, u.full_name AS passenger_name, u.avatar_url AS passenger_avatar_url,
                      o.expires_at
               FROM rides r
               JOIN users u ON u.id = r.passenger_id
               JOIN ride_driver_offers o ON o.ride_id = r.id AND o.driver_id = r.driver_id
               WHERE r.driver_id = ? AND r.status = 'DRIVER_ASSIGNED'
                 AND r.driver_response_status = 'PENDING' AND o.status = 'PENDING'
                 AND o.expires_at > CURRENT_TIMESTAMP
               ORDER BY r.created_at ASC""",
            (user["id"],)
        )
    active_ride = db.fetchone(
        """SELECT r.*, u.full_name AS passenger_name, u.phone AS passenger_phone,
                  u.avatar_url AS passenger_avatar_url
           FROM rides r
           JOIN users u ON u.id = r.passenger_id
           WHERE r.driver_id = ? AND r.status NOT IN ('COMPLETED', 'CANCELLED')
             AND r.driver_response_status = 'ACCEPTED'
           ORDER BY r.created_at DESC LIMIT 1""",
        (user["id"],)
    )

    return render_template(
        "driver/dashboard.html",
        user=user,
        profile=profile,
        vehicle=vehicle,
        total_earnings=total_earnings["total"],
        earnings_summary=earnings_summary,
        photo_count=photo_count,
        completion=completion,
        pending_rides=pending_rides,
        active_ride=active_ride,
        show_dispatch_sections=True
    )

@driver_bp.route("/api/earnings-summary")
def api_earnings_summary():
    """Real-time JSON endpoint for driver earnings summary and chart visualization."""
    user = AuthService.get_current_user()
    db = get_db()
    summary = get_driver_earnings_summary(user["id"], db)
    return jsonify({
        "success": True,
        "summary": summary,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

@driver_bp.route("/toggle-online", methods=["POST"])
def toggle_online():
    user = AuthService.get_current_user()
    db = get_db()
    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))

    if not profile or profile["verification_status"] != "APPROVED":
        flash("You must be an approved driver to go online.", "error")
        return redirect(url_for("driver.dashboard"))

    new_status = 0 if profile["is_online"] else 1
    if new_status:
        db.execute("UPDATE driver_profiles SET is_online = 1 WHERE user_id = ?", (user["id"],))
        waiting_rides = db.fetchall(
            """SELECT id FROM rides
               WHERE driver_id IS NULL AND status IN ('REQUESTED', 'SEARCHING_FOR_DRIVER')
               ORDER BY created_at ASC"""
        )
        for ride in waiting_rides:
            RideDispatchService.dispatch_ride(ride["id"])
        msg = "You are now ONLINE and available for ride requests."
    else:
        pending_rides = db.fetchall(
            """SELECT id, passenger_id FROM rides
               WHERE driver_id = ? AND status = 'DRIVER_ASSIGNED'
                 AND driver_response_status = 'PENDING'""",
            (user["id"],)
        )
        db.execute_transaction([
            ("UPDATE driver_profiles SET is_online = 0 WHERE user_id = ?", (user["id"],), 1),
            (
                """UPDATE rides SET driver_id = NULL, status = 'SEARCHING_FOR_DRIVER',
                          driver_response_status = 'DECLINED', updated_at = CURRENT_TIMESTAMP
                   WHERE driver_id = ? AND status = 'DRIVER_ASSIGNED'
                     AND driver_response_status = 'PENDING'""",
                (user["id"],)
            ),
            (
                """UPDATE ride_driver_offers
                   SET status = 'CANCELLED', responded_at = CURRENT_TIMESTAMP
                   WHERE driver_id = ? AND status = 'PENDING'""",
                (user["id"],)
            ),
        ])
        for pending_ride in pending_rides:
            still_unassigned = db.fetchone(
                """SELECT id FROM rides
                   WHERE id = ? AND driver_id IS NULL AND status = 'SEARCHING_FOR_DRIVER'""",
                (pending_ride["id"],)
            )
            if not still_unassigned:
                continue
            RideDispatchService.notify_passenger_driver_declined(
                pending_ride["id"], pending_ride["passenger_id"], user["full_name"]
            )
            if not RideDispatchService.dispatch_ride(
                pending_ride["id"], excluded_driver_ids={user["id"]}
            ):
                RideDispatchService.notify_passenger_no_driver(pending_ride["id"])
        msg = "You are now OFFLINE. Pending trip offers were returned for reassignment."
    flash(msg, "info")
    return redirect(url_for("driver.dashboard"))

@driver_bp.route("/requests")
def requests_list():
    user = AuthService.get_current_user()
    RideDispatchService.expire_stale_offers()
    db = get_db()
    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    pending_rides = []
    if profile and profile["is_online"] and profile["verification_status"] == "APPROVED":
        pending_rides = db.fetchall(
            """SELECT r.*, u.full_name as passenger_name, u.avatar_url as passenger_avatar_url,
                      o.expires_at
            FROM rides r
            JOIN users u ON r.passenger_id = u.id
            JOIN ride_driver_offers o ON o.ride_id = r.id AND o.driver_id = r.driver_id
            WHERE (
                (r.status = 'DRIVER_ASSIGNED' AND r.driver_id = ?
                    AND r.driver_response_status = 'PENDING')
            )
              AND o.status = 'PENDING' AND o.expires_at > CURRENT_TIMESTAMP
            ORDER BY r.created_at ASC""",
            (user["id"],)
        )
    return render_template(
        "driver/requests.html",
        user=user,
        profile=profile,
        pending_rides=pending_rides
    )

@driver_bp.route("/api/pending-offers")
def api_pending_offers():
    user = AuthService.get_current_user()
    RideDispatchService.expire_stale_offers()
    offers = get_db().fetchall(
        """SELECT r.id, r.pickup_address, r.destination_address, r.category,
                  r.estimated_distance_km, r.final_fare_ugx, r.estimated_fare_ugx,
                  o.expires_at
           FROM rides r
           JOIN ride_driver_offers o ON o.ride_id = r.id AND o.driver_id = r.driver_id
           WHERE r.driver_id = ? AND r.status = 'DRIVER_ASSIGNED'
             AND r.driver_response_status = 'PENDING' AND o.status = 'PENDING'
             AND o.expires_at > CURRENT_TIMESTAMP
             AND EXISTS (
               SELECT 1 FROM driver_profiles d
               WHERE d.user_id = r.driver_id AND d.is_online = 1
                 AND d.verification_status = 'APPROVED'
             )
           ORDER BY r.created_at DESC""",
        (user["id"],)
    )
    return jsonify({"success": True, "offers": offers})

@driver_bp.route("/active-ride")
def active_ride():
    user = AuthService.get_current_user()
    ride = get_db().fetchone(
        """SELECT r.*, u.full_name as passenger_name, u.phone as passenger_phone,
                  u.avatar_url as passenger_avatar_url
        FROM rides r
        JOIN users u ON r.passenger_id = u.id
        WHERE r.driver_id = ? AND r.status NOT IN ('COMPLETED', 'CANCELLED')
          AND (r.driver_response_status = 'ACCEPTED' OR r.status != 'DRIVER_ASSIGNED')
        ORDER BY r.created_at DESC LIMIT 1""",
        (user["id"],)
    )
    return render_template("driver/active_ride.html", user=user, ride=ride)

@driver_bp.route("/rides/<ride_id>/accept", methods=["POST"])
def accept_ride(ride_id):
    user = AuthService.get_current_user()
    db = get_db()
    RideDispatchService.expire_stale_offers(ride_id)

    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    if not profile or not profile["is_online"] or profile["verification_status"] != "APPROVED":
        flash("Only approved drivers who are online can accept trips.", "error")
        return redirect(url_for("driver.requests_list"))

    try:
        updated = db.execute_transaction([
            (
                """UPDATE rides
                   SET driver_id = ?, status = 'DRIVER_ASSIGNED',
                       driver_response_status = 'ACCEPTED', updated_at = CURRENT_TIMESTAMP
                   WHERE id = ? AND driver_id = ? AND status = 'DRIVER_ASSIGNED'
                     AND driver_response_status = 'PENDING'
                     AND EXISTS (
                       SELECT 1 FROM ride_driver_offers o
                       WHERE o.ride_id = rides.id AND o.driver_id = ?
                         AND o.status = 'PENDING' AND o.expires_at > CURRENT_TIMESTAMP
                     )
                     AND EXISTS (
                       SELECT 1 FROM driver_profiles d
                       WHERE d.user_id = ? AND d.is_online = 1
                         AND d.verification_status = 'APPROVED'
                     )
                     AND EXISTS (
                       SELECT 1 FROM users u WHERE u.id = ? AND u.is_active = 1
                     )
                     AND EXISTS (
                       SELECT 1 FROM vehicles v
                       WHERE v.driver_id = ? AND v.is_active = 1 AND v.is_verified = 1
                     )
                     AND NOT EXISTS (
                       SELECT 1 FROM rides active
                       WHERE active.driver_id = ? AND active.id != ?
                         AND active.status NOT IN ('COMPLETED', 'CANCELLED')
                     )""",
                (
                    user["id"], ride_id, user["id"], user["id"], user["id"], user["id"],
                    user["id"], user["id"], ride_id
                ),
                1
            ),
            (
                """UPDATE ride_driver_offers
                   SET status = 'ACCEPTED', responded_at = CURRENT_TIMESTAMP
                   WHERE ride_id = ? AND driver_id = ? AND status = 'PENDING'
                     AND expires_at > CURRENT_TIMESTAMP""",
                (ride_id, user["id"]),
                1
            )
        ])[0]
    except RuntimeError:
        current_offer = db.fetchone(
            "SELECT status FROM ride_driver_offers WHERE ride_id = ? AND driver_id = ?",
            (ride_id, user["id"])
        )
        still_pending = db.fetchone(
            """SELECT 1 AS pending FROM ride_driver_offers
               WHERE ride_id = ? AND driver_id = ? AND status = 'PENDING'
                 AND expires_at > CURRENT_TIMESTAMP""",
            (ride_id, user["id"])
        )
        if not current_offer or not still_pending:
            flash("This trip offer expired or was already handled.", "warning")
            return redirect(url_for("driver.requests_list"))
        eligible = db.fetchone(
            """SELECT 1 AS eligible
               FROM driver_profiles d
               JOIN users u ON u.id = d.user_id
               JOIN vehicles v ON v.driver_id = d.user_id
               WHERE d.user_id = ? AND d.is_online = 1
                 AND d.verification_status = 'APPROVED' AND u.is_active = 1
                 AND v.is_active = 1 AND v.is_verified = 1
                 AND NOT EXISTS (
                   SELECT 1 FROM rides active
                   WHERE active.driver_id = d.user_id AND active.id != ?
                     AND active.status NOT IN ('COMPLETED', 'CANCELLED')
                 )""",
            (user["id"], ride_id)
        )
        if not eligible:
            flash("You are no longer eligible to accept this trip. Check your online status and active rides.", "warning")
            return redirect(url_for("driver.requests_list"))
        raise
    if updated != 1:
        flash("This trip is no longer available, or you already have an active trip.", "warning")
        return redirect(url_for("driver.requests_list"))

    ride = db.fetchone("SELECT passenger_id FROM rides WHERE id = ?", (ride_id,))
    vehicle = db.fetchone("SELECT id, plate_number, make, model FROM vehicles WHERE driver_id = ?", (user["id"],))
    if ride:
        veh_str = f" ({vehicle['plate_number']} {vehicle['make']} {vehicle['model']})" if vehicle else ""
        photos_hint = ""
        if vehicle and VehiclePhotoService.count_photos(vehicle["id"]):
            photos_hint = " Open your trip page to see photos of the car so you can spot it easily."
        NotificationService.create_notification(
            user_id=ride["passenger_id"],
            title="Driver accepted your ride",
            message=f"{user['full_name']}{veh_str} accepted your ride #{ride_id[:8].upper()}. Live trip updates are now active.{photos_hint}",
            notif_type="DRIVER_ASSIGNED",
            related_entity_id=ride_id
        )

    flash("Ride accepted. You can now start trip updates.", "success")
    return redirect(url_for("driver.active_ride"))

@driver_bp.route("/rides/<ride_id>/decline", methods=["POST"])
def decline_ride(ride_id):
    user = AuthService.get_current_user()
    db = get_db()
    RideDispatchService.expire_stale_offers(ride_id)
    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    if not profile or not profile["is_online"] or profile["verification_status"] != "APPROVED":
        flash("Only approved online drivers can respond to trip offers.", "error")
        return redirect(url_for("driver.requests_list"))

    ride = db.fetchone(
        """SELECT passenger_id FROM rides
           WHERE id = ? AND driver_id = ? AND status = 'DRIVER_ASSIGNED'
             AND driver_response_status = 'PENDING'""",
        (ride_id, user["id"])
    )
    if not ride:
        flash("This trip offer is no longer awaiting your response.", "warning")
        return redirect(url_for("driver.requests_list"))

    try:
        declined = RideDispatchService.decline_offer(ride_id, user["id"])
    except RuntimeError:
        current_offer = db.fetchone(
            """SELECT 1 AS pending FROM ride_driver_offers
               WHERE ride_id = ? AND driver_id = ? AND status = 'PENDING'
                 AND expires_at > CURRENT_TIMESTAMP""",
            (ride_id, user["id"])
        )
        if not current_offer:
            declined = False
        else:
            raise
    if not declined:
        flash("This trip offer is no longer available.", "warning")
        return redirect(url_for("driver.requests_list"))

    RideDispatchService.notify_passenger_driver_declined(
        ride_id, ride["passenger_id"], user["full_name"]
    )
    if not RideDispatchService.dispatch_ride(ride_id):
        RideDispatchService.notify_passenger_no_driver(ride_id)
    flash("You declined the trip. RideEasy will seek another available driver.", "info")
    return redirect(url_for("driver.requests_list"))

@driver_bp.route("/rides/<ride_id>/status", methods=["POST"])
def update_ride_status(ride_id):
    user = AuthService.get_current_user()
    db = get_db()

    new_status = request.form.get("status")
    allowed_transitions = {
        "DRIVER_ASSIGNED": "DRIVER_ARRIVING",
        "DRIVER_ARRIVING": "DRIVER_ARRIVED",
        "DRIVER_ARRIVED": "TRIP_STARTED",
        "TRIP_STARTED": "TRIP_COMPLETED",
        "TRIP_COMPLETED": "COMPLETED"
    }

    ride = db.fetchone(
        """SELECT * FROM rides
           WHERE id = ? AND driver_id = ? AND driver_response_status = 'ACCEPTED'""",
        (ride_id, user["id"])
    )
    if not ride:
        abort(404)

    expected = allowed_transitions.get(ride["status"])
    if new_status != expected:
        flash(f"Invalid status transition from {ride['status']} to {new_status}.", "error")
        return redirect(url_for("driver.active_ride"))

    transition = (
        """UPDATE rides SET status = ?, updated_at = CURRENT_TIMESTAMP
           WHERE id = ? AND driver_id = ? AND status = ?
             AND driver_response_status = 'ACCEPTED'""",
        (new_status, ride_id, user["id"], ride["status"]),
        1
    )
    if new_status == "COMPLETED":
        try:
            db.execute_transaction([
                transition,
                ("UPDATE driver_profiles SET total_trips = total_trips + 1 WHERE user_id = ?", (user["id"],), 1),
            ])
        except RuntimeError:
            current_ride = db.fetchone("SELECT status FROM rides WHERE id = ?", (ride_id,))
            if current_ride and current_ride["status"] in ("CANCELLED", "COMPLETED"):
                flash("This ride has already changed and cannot be completed again.", "warning")
                return redirect(url_for("driver.active_ride"))
            raise
        flash("Trip completed. Passenger payment remains pending until verified by Paystack.", "success")
        return redirect(url_for("driver.trips"))
    else:
        try:
            db.execute_transaction([transition])
        except RuntimeError:
            current_ride = db.fetchone("SELECT status FROM rides WHERE id = ?", (ride_id,))
            if not current_ride or current_ride["status"] == ride["status"]:
                raise
            flash("This ride changed before the status update could be saved.", "warning")
            return redirect(url_for("driver.active_ride"))
        passenger_title = {
            "DRIVER_ARRIVING": "Driver is heading to pickup",
            "DRIVER_ARRIVED": "Driver arrived at pickup",
            "TRIP_STARTED": "Your ride has started",
            "TRIP_COMPLETED": "Your trip is complete",
        }[new_status]
        NotificationService.create_notification(
            user_id=ride["passenger_id"],
            title=passenger_title,
            message=f"Ride #{ride_id[:8].upper()} status: {new_status.replace('_', ' ').lower()}.",
            notif_type="DRIVER_ASSIGNED",
            related_entity_id=ride_id
        )
        flash(f"Trip status updated to {new_status.replace('_', ' ').title()}.", "info")

    return redirect(url_for("driver.active_ride"))

@driver_bp.route("/trips")
def trips():
    user = AuthService.get_current_user()
    db = get_db()
    trips_list = db.fetchall(
        """SELECT r.*, u.full_name as passenger_name, u.phone as passenger_phone,
                  u.avatar_url as passenger_avatar_url
        FROM rides r
        JOIN users u ON r.passenger_id = u.id
        WHERE r.driver_id = ? AND r.status = 'COMPLETED'
        ORDER BY r.created_at DESC""",
        (user["id"],)
    )
    return render_template("driver/trips.html", user=user, trips=trips_list)

def _profile_form_values(profile, vehicle):
    """Starting values for the work-profile form, hiding registration placeholders."""
    profile = profile or {}
    vehicle = vehicle or {}
    return {
        "date_of_birth": profile.get("date_of_birth") or "",
        "years_experience": "" if not profile.get("date_of_birth") else profile.get("years_experience", ""),
        "license_number": profile_rules.display_value(profile.get("license_number")),
        "national_id_nin": profile_rules.display_value(profile.get("national_id_nin")),
        "category": vehicle.get("category", ""),
        "make": vehicle.get("make", ""),
        "model": vehicle.get("model", ""),
        "year": vehicle.get("year", ""),
        "color": vehicle.get("color", ""),
        "plate_number": vehicle.get("plate_number", ""),
        "capacity": vehicle.get("capacity", ""),
    }

def _years_ago(day, years):
    """The same calendar day `years` ago (29 Feb becomes 28 Feb in non-leap years)."""
    try:
        return day.replace(year=day.year - years)
    except ValueError:
        return day.replace(year=day.year - years, day=28)

def _render_profile_form(user, profile, vehicle, form, errors, status=200):
    photos = VehiclePhotoService.photo_status(vehicle["id"]) if vehicle else []
    photo_count = sum(1 for p in photos if p["has_photo"])
    today = date.today()
    return render_template(
        "driver/profile.html",
        user=user,
        profile=profile,
        vehicle=vehicle,
        form=form,
        errors=errors,
        photos=photos,
        photo_count=photo_count,
        completion=profile_rules.completeness(profile, vehicle, photo_count),
        categories=profile_rules.VEHICLE_CATEGORIES,
        age=profile_rules.age_from_dob(profile.get("date_of_birth")) if profile else None,
        dob_min=_years_ago(today, profile_rules.MAX_DRIVER_AGE).isoformat(),
        dob_max=_years_ago(today, profile_rules.MIN_DRIVER_AGE).isoformat(),
        year_max=today.year + 1,
    ), status

@driver_bp.route("/profile", methods=["GET", "POST"])
def profile():
    """Driver work profile: identity, licence, experience and vehicle details."""
    user = AuthService.get_current_user()
    if user["role"] != "DRIVER":
        abort(403)
    db = get_db()
    profile_row = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    vehicle = db.fetchone("SELECT * FROM vehicles WHERE driver_id = ?", (user["id"],))

    if request.method == "GET":
        return _render_profile_form(user, profile_row, vehicle, _profile_form_values(profile_row, vehicle), {})

    if not _csrf_ok():
        flash("Your session expired. Reload the page and try again.", "error")
        return redirect(url_for("driver.profile"))

    clean, errors = profile_rules.validate_profile(request.form)
    if not errors:
        taken = db.fetchone(
            "SELECT 1 AS taken FROM vehicles WHERE plate_number = ? AND (driver_id IS NULL OR driver_id != ?)",
            (clean["plate_number"], user["id"])
        )
        if taken:
            errors["plate_number"] = "This number plate is already registered to another driver."
    if errors:
        flash("Please fix the highlighted fields and save again.", "error")
        # Keep what the driver typed (sensitive values stay in the form, never in logs).
        form = {key: request.form.get(key, "") for key in _profile_form_values(None, None)}
        return _render_profile_form(user, profile_row, vehicle, form, errors, 400)

    needs_review = bool(
        profile_row
        and profile_row["verification_status"] == "APPROVED"
        and profile_rules.sensitive_fields_changed(profile_row, vehicle, clean)
    )

    operations = []
    if profile_row:
        sets = "license_number = ?, national_id_nin = ?, years_experience = ?, date_of_birth = ?"
        if needs_review:
            sets += ", verification_status = 'PENDING', is_online = 0"
        operations.append((
            f"UPDATE driver_profiles SET {sets} WHERE user_id = ?",
            (clean["license_number"], clean["national_id_nin"], clean["years_experience"],
             clean["date_of_birth"], user["id"]),
            1
        ))
    else:
        operations.append((
            """INSERT INTO driver_profiles
               (user_id, license_number, national_id_nin, years_experience, date_of_birth, verification_status)
               VALUES (?, ?, ?, ?, ?, 'PENDING')""",
            (user["id"], clean["license_number"], clean["national_id_nin"],
             clean["years_experience"], clean["date_of_birth"]),
            1
        ))
    vehicle_values = (clean["make"], clean["model"], clean["year"], clean["color"],
                      clean["plate_number"], clean["category"], clean["capacity"])
    if vehicle:
        operations.append((
            """UPDATE vehicles SET make = ?, model = ?, year = ?, color = ?,
                      plate_number = ?, category = ?, capacity = ?
               WHERE id = ? AND driver_id = ?""",
            vehicle_values + (vehicle["id"], user["id"]),
            1
        ))
    else:
        operations.append((
            """INSERT INTO vehicles
               (id, driver_id, make, model, year, color, plate_number, category, capacity)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (f"veh_{uuid.uuid4().hex[:10]}", user["id"]) + vehicle_values,
            1
        ))
    if needs_review:
        operations.append((
            "UPDATE users SET is_verified = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (user["id"],),
            1
        ))
    # The audit entry records that the profile changed, never the ID numbers themselves.
    operations.append((
        "INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (f"aud_{uuid.uuid4().hex[:8]}", user["id"], "DRIVER_PROFILE_UPDATED", "DRIVER_PROFILE", user["id"],
         "Work profile updated; sent back for admin review" if needs_review else "Work profile updated"),
        1
    ))

    try:
        db.execute_transaction(operations)
    except Exception:
        current_app.logger.exception("Driver profile save failed for %s", user["id"])
        still_taken = db.fetchone(
            "SELECT 1 AS taken FROM vehicles WHERE plate_number = ? AND (driver_id IS NULL OR driver_id != ?)",
            (clean["plate_number"], user["id"])
        )
        if still_taken:
            flash("This number plate is already registered to another driver.", "error")
        else:
            flash("We could not save your profile. Please try again.", "error")
        form = {key: request.form.get(key, "") for key in _profile_form_values(None, None)}
        return _render_profile_form(
            user, profile_row, vehicle, form,
            {"plate_number": "This number plate is already registered to another driver."} if still_taken else {},
            400 if still_taken else 500
        )

    if needs_review:
        flash("Profile saved. Because your ID, permit or number plate changed, an admin must approve it "
              "again before you can go online.", "warning")
    elif not profile_row or profile_row["verification_status"] == "PENDING":
        flash("Profile saved. RideEasy will review your details. Next, add photos of your car.", "success")
    else:
        flash("Profile saved.", "success")
    # A driver who has just registered a car for the first time goes straight to the photos step.
    if not vehicle:
        return redirect(url_for("vehicle_photos.manage"))
    return redirect(url_for("driver.profile"))

@driver_bp.route("/verification")
def verification():
    user = AuthService.get_current_user()
    db = get_db()
    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    vehicle = db.fetchone("SELECT * FROM vehicles WHERE driver_id = ?", (user["id"],))
    documents = db.fetchall("SELECT * FROM driver_documents WHERE driver_id = ?", (user["id"],))
    return render_template(
        "driver/verification.html", user=user, profile=profile, vehicle=vehicle, documents=documents,
        permit_display=profile_rules.display_value(profile["license_number"]) if profile else "",
        nin_masked=profile_rules.mask_identifier(profile["national_id_nin"]) if profile else "Not provided",
        age=profile_rules.age_from_dob(profile.get("date_of_birth")) if profile else None,
    )
