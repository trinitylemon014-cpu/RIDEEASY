from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort, jsonify
from app.repositories.database import get_db
from app.services.auth_service import login_required, role_required, AuthService
from app.services.ride_dispatch_service import RideDispatchService
from app.services.notification_service import NotificationService

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
    if new_status:
        db.execute("UPDATE driver_profiles SET is_online = 1 WHERE user_id = ?", (user["id"],))
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
            )
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
            RideDispatchService.dispatch_ride(
                pending_ride["id"], excluded_driver_ids={user["id"]}
            )
        msg = "You are now OFFLINE. Pending trip offers were returned for reassignment."
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
            WHERE (
                (r.status = 'DRIVER_ASSIGNED' AND r.driver_id = ?
                    AND r.driver_response_status = 'PENDING')
                OR (r.status IN ('REQUESTED', 'SEARCHING_FOR_DRIVER') AND r.driver_id IS NULL
                    AND NOT EXISTS (
                        SELECT 1 FROM rides active
                        WHERE active.driver_id = ? AND active.status NOT IN ('COMPLETED', 'CANCELLED')
                    ))
            )
            ORDER BY CASE WHEN r.driver_id = ? THEN 0 ELSE 1 END, r.created_at DESC""",
            (user["id"], user["id"], user["id"])
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
    offers = get_db().fetchall(
        """SELECT id, pickup_address, destination_address
           FROM rides
           WHERE driver_id = ? AND status = 'DRIVER_ASSIGNED'
             AND driver_response_status = 'PENDING'
           ORDER BY created_at DESC""",
        (user["id"],)
    )
    return jsonify({"success": True, "offers": offers})

@driver_bp.route("/active-ride")
def active_ride():
    user = AuthService.get_current_user()
    ride = get_db().fetchone(
        """SELECT r.*, u.full_name as passenger_name, u.phone as passenger_phone
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

    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    if not profile or not profile["is_online"] or profile["verification_status"] != "APPROVED":
        flash("Only approved drivers who are online can accept trips.", "error")
        return redirect(url_for("driver.requests_list"))

    updated = db.execute_transaction([
        (
            """UPDATE rides
               SET driver_id = ?, status = 'DRIVER_ASSIGNED',
                   driver_response_status = 'ACCEPTED', updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND (
                   (driver_id = ? AND status = 'DRIVER_ASSIGNED' AND driver_response_status = 'PENDING')
                   OR (driver_id IS NULL AND status IN ('REQUESTED', 'SEARCHING_FOR_DRIVER'))
               )
                 AND EXISTS (
                   SELECT 1 FROM driver_profiles d
                   WHERE d.user_id = ? AND d.is_online = 1 AND d.verification_status = 'APPROVED'
                 )
                 AND EXISTS (
                   SELECT 1 FROM users u WHERE u.id = ? AND u.is_active = 1
                 )
                 AND NOT EXISTS (
                   SELECT 1 FROM rides active
                   WHERE active.driver_id = ? AND active.id != ?
                     AND active.status NOT IN ('COMPLETED', 'CANCELLED')
                 )""",
            (user["id"], ride_id, user["id"], user["id"], user["id"], user["id"], ride_id)
        )
    ])[0]
    if updated != 1:
        flash("This trip is no longer available, or you already have an active trip.", "warning")
        return redirect(url_for("driver.requests_list"))

    ride = db.fetchone("SELECT passenger_id FROM rides WHERE id = ?", (ride_id,))
    vehicle = db.fetchone("SELECT plate_number, make, model FROM vehicles WHERE driver_id = ?", (user["id"],))
    if ride:
        veh_str = f" ({vehicle['plate_number']} {vehicle['make']} {vehicle['model']})" if vehicle else ""
        NotificationService.create_notification(
            user_id=ride["passenger_id"],
            title="Driver accepted your ride",
            message=f"{user['full_name']}{veh_str} accepted your ride #{ride_id[:8].upper()}. Live trip updates are now active.",
            notif_type="DRIVER_ASSIGNED",
            related_entity_id=ride_id
        )

    flash("Ride accepted. You can now start trip updates.", "success")
    return redirect(url_for("driver.active_ride"))

@driver_bp.route("/rides/<ride_id>/decline", methods=["POST"])
def decline_ride(ride_id):
    user = AuthService.get_current_user()
    db = get_db()
    profile = db.fetchone("SELECT * FROM driver_profiles WHERE user_id = ?", (user["id"],))
    if not profile or not profile["is_online"] or profile["verification_status"] != "APPROVED":
        flash("Only approved online drivers can respond to trip offers.", "error")
        return redirect(url_for("driver.requests_list"))

    ride = db.fetchone(
        "SELECT passenger_id FROM rides WHERE id = ? AND driver_id = ? AND status = 'DRIVER_ASSIGNED' AND driver_response_status = 'PENDING'",
        (ride_id, user["id"])
    )
    if not ride:
        flash("This trip offer is no longer awaiting your response.", "warning")
        return redirect(url_for("driver.requests_list"))

    updated = db.execute_transaction([
        (
            """UPDATE rides SET driver_id = NULL, status = 'SEARCHING_FOR_DRIVER',
                      driver_response_status = 'DECLINED', updated_at = CURRENT_TIMESTAMP
               WHERE id = ? AND driver_id = ? AND status = 'DRIVER_ASSIGNED'
                 AND driver_response_status = 'PENDING'""",
            (ride_id, user["id"]), 1
        )
    ])[0]
    if updated != 1:
        flash("This trip offer is no longer available.", "warning")
        return redirect(url_for("driver.requests_list"))

    RideDispatchService.notify_passenger_driver_declined(
        ride_id, ride["passenger_id"], user["full_name"]
    )
    RideDispatchService.dispatch_ride(ride_id, excluded_driver_ids={user["id"]})
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

    ride = db.fetchone("SELECT * FROM rides WHERE id = ? AND driver_id = ?", (ride_id, user["id"]))
    if not ride:
        abort(404)

    expected = allowed_transitions.get(ride["status"])
    if new_status != expected:
        flash(f"Invalid status transition from {ride['status']} to {new_status}.", "error")
        return redirect(url_for("driver.active_ride"))

    if new_status == "COMPLETED":
        db.execute(
            "UPDATE rides SET status = 'COMPLETED', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (ride_id,)
        )
        db.execute(
            "UPDATE driver_profiles SET total_trips = total_trips + 1 WHERE user_id = ?",
            (user["id"],)
        )
        flash("Trip completed. Passenger payment remains pending until verified by Paystack.", "success")
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
