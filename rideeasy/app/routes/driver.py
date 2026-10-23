from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, jsonify
from app.repositories.database import get_db
from app.services.auth_service import login_required, role_required, AuthService

driver_bp = Blueprint("driver", __name__, url_prefix="/driver")

@driver_bp.before_request
@login_required
@role_required("DRIVER", "ADMIN")
def before_request():
    pass

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
                  r.created_at, date(r.created_at) as trip_date,
                  u.full_name as passenger_name
        FROM rides r
        JOIN users u ON r.passenger_id = u.id
        WHERE r.driver_id = ? AND r.status = 'COMPLETED' AND r.created_at >= ?
        ORDER BY r.created_at ASC""",
        (driver_id, earliest_date)
    )

    for r in rides:
        trip_date = r["trip_date"]
        fare = r["final_fare_ugx"] or r["estimated_fare_ugx"] or 0
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
        """SELECT COALESCE(SUM(COALESCE(final_fare_ugx, estimated_fare_ugx)), 0) as total
        FROM rides WHERE driver_id = ? AND status = 'COMPLETED'""",
        (user["id"],)
    )

    earnings_summary = get_driver_earnings_summary(user["id"], db)

    return render_template(
        "driver/dashboard.html",
        user=user,
        profile=profile,
        vehicle=vehicle,
        total_earnings=total_earnings["total"],
        earnings_summary=earnings_summary,
        show_dispatch_sections=False
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
    db.execute("UPDATE driver_profiles SET is_online = ? WHERE user_id = ?", (new_status, user["id"]))

    msg = "You are now ONLINE and available for ride requests." if new_status else "You are now OFFLINE."
    flash(msg, "info")
    return redirect(url_for("driver.dashboard"))

@driver_bp.route("/requests")
def requests_list():
    user = AuthService.get_current_user()
    db = get_db()
    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    pending_rides = []
    if profile and profile["is_online"] and profile["verification_status"] == "APPROVED":
        pending_rides = db.fetchall(
            """SELECT r.*, u.full_name as passenger_name, u.phone as passenger_phone
            FROM rides r
            JOIN users u ON r.passenger_id = u.id
            WHERE r.status IN ('REQUESTED', 'SEARCHING_FOR_DRIVER')
            ORDER BY r.created_at DESC"""
        )
    return render_template(
        "driver/requests.html",
        user=user,
        profile=profile,
        pending_rides=pending_rides
    )

@driver_bp.route("/active-ride")
def active_ride():
    user = AuthService.get_current_user()
    ride = get_db().fetchone(
        """SELECT r.*, u.full_name as passenger_name, u.phone as passenger_phone
        FROM rides r
        JOIN users u ON r.passenger_id = u.id
        WHERE r.driver_id = ? AND r.status NOT IN ('COMPLETED', 'CANCELLED')
        ORDER BY r.created_at DESC LIMIT 1""",
        (user["id"],)
    )
    return render_template("driver/active_ride.html", user=user, ride=ride)

@driver_bp.route("/rides/<ride_id>/accept", methods=["POST"])
def accept_ride(ride_id):
    user = AuthService.get_current_user()
    db = get_db()

    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    if not profile or profile["verification_status"] != "APPROVED":
        flash("Only verified drivers can accept trips.", "error")
        return redirect(url_for("driver.requests_list"))

    # Atomically assign driver
    db.execute(
        "UPDATE rides SET driver_id = ?, status = 'DRIVER_ASSIGNED' WHERE id = ? AND (driver_id IS NULL OR driver_id = ?)",
        (user["id"], ride_id, user["id"])
    )

    # In-App Notification: Notify passenger that driver has accepted
    ride = db.fetchone("SELECT passenger_id, pickup_address FROM rides WHERE id = ?", (ride_id,))
    vehicle = db.fetchone("SELECT plate_number, make, model FROM vehicles WHERE driver_id = ?", (user["id"],))
    if ride:
        from app.services.notification_service import NotificationService
        veh_str = f" ({vehicle['plate_number']} {vehicle['make']} {vehicle['model']})" if vehicle else ""
        NotificationService.create_notification(
            user_id=ride["passenger_id"],
            title="Driver Assigned",
            message=f"{user['full_name']}{veh_str} accepted your ride #{ride_id[:8].upper()} and is en route to pickup.",
            notif_type="DRIVER_ASSIGNED",
            related_entity_id=ride_id
        )

    flash("Ride accepted! Proceed to pickup location.", "success")
    return redirect(url_for("driver.active_ride"))

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

    ride = db.fetchone("SELECT * FROM rides WHERE id = ? AND driver_id = ?", (ride_id, user["id"]))
    if not ride:
        abort(404)

    expected = allowed_transitions.get(ride["status"])
    if new_status != expected and new_status != "COMPLETED":
        flash(f"Invalid status transition from {ride['status']} to {new_status}.", "error")
        return redirect(url_for("driver.active_ride"))

    if new_status == "COMPLETED":
        db.execute(
            "UPDATE rides SET status = 'COMPLETED', payment_status = 'PAID', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (ride_id,)
        )
        db.execute(
            "UPDATE driver_profiles SET total_trips = total_trips + 1 WHERE user_id = ?",
            (user["id"],)
        )
        flash("Trip completed successfully! Fare recorded.", "success")
        return redirect(url_for("driver.trips"))
    else:
        db.execute(
            "UPDATE rides SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (new_status, ride_id)
        )
        flash(f"Trip status updated to {new_status.replace('_', ' ').title()}.", "info")

    return redirect(url_for("driver.active_ride"))

@driver_bp.route("/trips")
def trips():
    user = AuthService.get_current_user()
    db = get_db()
    trips_list = db.fetchall(
        """SELECT r.*, u.full_name as passenger_name, u.phone as passenger_phone
        FROM rides r
        JOIN users u ON r.passenger_id = u.id
        WHERE r.driver_id = ? AND r.status = 'COMPLETED'
        ORDER BY r.created_at DESC""",
        (user["id"],)
    )
    return render_template("driver/trips.html", user=user, trips=trips_list)

@driver_bp.route("/verification")
def verification():
    user = AuthService.get_current_user()
    db = get_db()
    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    vehicle = db.fetchone("SELECT * FROM vehicles WHERE driver_id = ?", (user["id"],))
    documents = db.fetchall("SELECT * FROM driver_documents WHERE driver_id = ?", (user["id"],))
    return render_template("driver/verification.html", user=user, profile=profile, vehicle=vehicle, documents=documents)
