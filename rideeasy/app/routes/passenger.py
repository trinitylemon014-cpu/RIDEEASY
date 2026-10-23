import uuid
from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify, abort
from app.repositories.database import get_db
from app.services.auth_service import login_required, role_required, AuthService
from app.services.pricing_service import MapService, PricingService
from app.services.payment_service import PaymentService
from app.services.notification_service import NotificationService

passenger_bp = Blueprint("passenger", __name__, url_prefix="/passenger")

@passenger_bp.before_request
@login_required
@role_required("PASSENGER", "ADMIN")
def before_request():
    pass

REWARD_BENEFITS_CATALOG = [
    {
        "id": "rew_toll_pass",
        "title": "Entebbe Express Toll Pass",
        "category": "AIRPORT & EXPRESSWAY",
        "points_cost": 200,
        "required_km": 20,
        "discount_ugx": 5000,
        "description": "Complimentary digital electronic toll pass for the Entebbe Expressway toll gate.",
        "badge": "AIRPORT SPECIAL"
    },
    {
        "id": "rew_city_discount_5k",
        "title": "UGX 5,000 Off Any City Trip",
        "category": "RIDE DISCOUNT",
        "points_cost": 350,
        "required_km": 35,
        "discount_ugx": 5000,
        "description": "Direct UGX 5,000 fare deduction on Boda, Economy, or Comfort rides across Kampala.",
        "badge": "POPULAR"
    },
    {
        "id": "rew_airport_discount_10k",
        "title": "UGX 10,000 Off Airport Ride",
        "category": "AIRPORT SPECIAL",
        "points_cost": 600,
        "required_km": 60,
        "discount_ugx": 10000,
        "description": "Direct UGX 10,000 savings on direct transfers to or from Entebbe International Airport (EBB).",
        "badge": "SAVER"
    },
    {
        "id": "rew_comfort_upgrade",
        "title": "Free Comfort Vehicle Upgrade",
        "category": "PREMIUM PERK",
        "points_cost": 800,
        "required_km": 80,
        "discount_ugx": 8000,
        "description": "Book Economy tariff and receive an instant complimentary upgrade to a climate-controlled Comfort vehicle.",
        "badge": "UPGRADE"
    },
    {
        "id": "rew_baggage_allowance",
        "title": "10kg Flight Baggage Voucher",
        "category": "TRAVEL DESK PARTNER",
        "points_cost": 1200,
        "required_km": 120,
        "discount_ugx": 35000,
        "description": "Extra baggage credit voucher redeemable via Nile Equatorial Travel Agency for regional flights.",
        "badge": "FLIGHT PERK"
    },
    {
        "id": "rew_vip_lounge",
        "title": "Entebbe Airport VIP Lounge Pass",
        "category": "VIP PRIVILEGE",
        "points_cost": 1800,
        "required_km": 180,
        "discount_ugx": 65000,
        "description": "Complimentary 3-hour access pass to Karibuni VIP Lounge at Entebbe Airport with refreshments and Wi-Fi.",
        "badge": "EXCLUSIVE"
    }
]

def get_passenger_rewards_summary(passenger_id, db):
    """
    Computes accumulated RideEasy Rewards points, tier status, distance milestone progress,
    and active vouchers based on total trip distance from completed rides.
    """
    stats = db.fetchone(
        """SELECT COALESCE(SUM(estimated_distance_km), 0) as total_distance_km,
                  COUNT(*) as completed_count
           FROM rides
           WHERE passenger_id = ? AND status = 'COMPLETED'""",
        (passenger_id,)
    )
    total_km = round(float(stats["total_distance_km"]), 1) if stats else 0.0
    completed_count = int(stats["completed_count"]) if stats else 0

    POINTS_PER_KM = 10
    total_earned_points = int(round(total_km * POINTS_PER_KM))

    spent_row = db.fetchone(
        "SELECT COALESCE(SUM(points_spent), 0) as total_spent FROM rewards_redemptions WHERE passenger_id = ?",
        (passenger_id,)
    )
    total_spent_points = int(spent_row["total_spent"]) if spent_row else 0
    available_points = max(0, total_earned_points - total_spent_points)

    if total_earned_points >= 1500:
        tier_name = "VIP Diamond Club"
        tier_code = "DIAMOND"
        next_tier_name = "Max Tier Reached"
        tier_min = 1500
        tier_max = 1500
        progress_pct = 100
        points_to_next = 0
        km_to_next = 0.0
    elif total_earned_points >= 750:
        tier_name = "Platinum Traveler"
        tier_code = "PLATINUM"
        next_tier_name = "VIP Diamond Club"
        tier_min = 750
        tier_max = 1500
        progress_pct = min(100, int(((total_earned_points - 750) / (1500 - 750)) * 100))
        points_to_next = 1500 - total_earned_points
        km_to_next = round(points_to_next / POINTS_PER_KM, 1)
    elif total_earned_points >= 250:
        tier_name = "Gold Commuter"
        tier_code = "GOLD"
        next_tier_name = "Platinum Traveler"
        tier_min = 250
        tier_max = 750
        progress_pct = min(100, int(((total_earned_points - 250) / (750 - 250)) * 100))
        points_to_next = 750 - total_earned_points
        km_to_next = round(points_to_next / POINTS_PER_KM, 1)
    else:
        tier_name = "Silver Cruiser"
        tier_code = "SILVER"
        next_tier_name = "Gold Commuter"
        tier_min = 0
        tier_max = 250
        progress_pct = min(100, int((total_earned_points / 250) * 100))
        points_to_next = 250 - total_earned_points
        km_to_next = round(points_to_next / POINTS_PER_KM, 1)

    redemptions = db.fetchall(
        """SELECT * FROM rewards_redemptions
           WHERE passenger_id = ?
           ORDER BY created_at DESC""",
        (passenger_id,)
    )

    benefits = []
    for item in REWARD_BENEFITS_CATALOG:
        unlocked = available_points >= item["points_cost"]
        needed_points = max(0, item["points_cost"] - available_points)
        needed_km = round(needed_points / POINTS_PER_KM, 1)
        benefits.append({
            **item,
            "can_redeem": unlocked,
            "needed_points": needed_points,
            "needed_km": needed_km
        })

    return {
        "total_km": total_km,
        "completed_count": completed_count,
        "points_per_km": POINTS_PER_KM,
        "total_earned_points": total_earned_points,
        "total_spent_points": total_spent_points,
        "available_points": available_points,
        "tier_name": tier_name,
        "tier_code": tier_code,
        "next_tier_name": next_tier_name,
        "tier_min": tier_min,
        "tier_max": tier_max,
        "progress_pct": progress_pct,
        "points_to_next": points_to_next,
        "km_to_next": km_to_next,
        "benefits": benefits,
        "redemptions": redemptions
    }

@passenger_bp.route("/dashboard")
def dashboard():
    user = AuthService.get_current_user()
    db = get_db()
    search_query = request.args.get("q", "").strip()

    # Active and recent rides with ratings
    recent_query = """SELECT r.*, u.full_name as driver_name, v.plate_number, v.make, v.model,
                             rr.rating as user_rating, rr.review as user_review
    FROM rides r
    LEFT JOIN users u ON r.driver_id = u.id
    LEFT JOIN vehicles v ON v.driver_id = u.id
    LEFT JOIN ride_ratings rr ON rr.ride_id = r.id AND rr.passenger_id = r.passenger_id
    WHERE r.passenger_id = ?"""
    recent_params = [user["id"]]

    if search_query:
        recent_query += """ AND (
            r.pickup_address LIKE ? OR
            r.destination_address LIKE ? OR
            u.full_name LIKE ? OR
            r.created_at LIKE ? OR
            r.id LIKE ?
        )"""
        q_pattern = f"%{search_query}%"
        recent_params.extend([q_pattern, q_pattern, q_pattern, q_pattern, q_pattern])

    recent_query += " ORDER BY r.created_at DESC LIMIT 10"
    recent_rides = db.fetchall(recent_query, tuple(recent_params))

    # Dedicated Completed rides with ratings
    completed_query = """SELECT r.*, u.full_name as driver_name, u.phone as driver_phone,
                               v.plate_number, v.make, v.model,
                               rr.rating as user_rating, rr.review as user_review
    FROM rides r
    LEFT JOIN users u ON r.driver_id = u.id
    LEFT JOIN vehicles v ON v.driver_id = u.id
    LEFT JOIN ride_ratings rr ON rr.ride_id = r.id AND rr.passenger_id = r.passenger_id
    WHERE r.passenger_id = ? AND r.status = 'COMPLETED'"""
    completed_params = [user["id"]]

    if search_query:
        completed_query += """ AND (
            r.pickup_address LIKE ? OR
            r.destination_address LIKE ? OR
            u.full_name LIKE ? OR
            r.created_at LIKE ? OR
            r.id LIKE ?
        )"""
        q_pattern = f"%{search_query}%"
        completed_params.extend([q_pattern, q_pattern, q_pattern, q_pattern, q_pattern])

    completed_query += " ORDER BY r.created_at DESC LIMIT 10"
    completed_rides = db.fetchall(completed_query, tuple(completed_params))

    # Confirmed Journeys & Flight Requests
    journeys = db.fetchall(
        """SELECT j.*, b.booking_reference_pnr, b.airline_name, b.flight_number
        FROM confirmed_journeys j
        JOIN flight_bookings b ON j.flight_booking_id = b.id
        WHERE j.passenger_id = ?
        ORDER BY j.departure_datetime ASC""",
        (user["id"],)
    )

    flight_requests = db.fetchall(
        """SELECT r.*, c.company_name
        FROM flight_requests r
        LEFT JOIN travel_companies c ON r.assigned_company_id = c.user_id
        WHERE r.passenger_id = ?
        ORDER BY r.created_at DESC LIMIT 3""",
        (user["id"],)
    )

    # Active reminders
    reminders = db.fetchall(
        """SELECT r.*, j.origin, j.destination, j.departure_datetime
        FROM journey_reminders r
        JOIN confirmed_journeys j ON r.journey_id = j.id
        WHERE j.passenger_id = ?
        ORDER BY r.scheduled_for ASC LIMIT 5""",
        (user["id"],)
    )

    from app.services.notification_service import NotificationService
    notifications = NotificationService.get_user_notifications(user["id"], limit=10)

    # RideEasy Rewards points, tier status, and benefits summary
    rewards_summary = get_passenger_rewards_summary(user["id"], db)

    return render_template(
        "passenger/dashboard.html",
        user=user,
        recent_rides=recent_rides,
        completed_rides=completed_rides,
        journeys=journeys,
        flight_requests=flight_requests,
        reminders=reminders,
        notifications=notifications,
        search_query=search_query,
        rewards_summary=rewards_summary
    )

@passenger_bp.route("/rewards/redeem", methods=["POST"])
def redeem_reward():
    """Redeems an accumulated points benefit for a travel voucher or fare discount."""
    user = AuthService.get_current_user()
    db = get_db()

    data = request.get_json(silent=True) or request.form
    reward_id = data.get("reward_id", "").strip()

    benefit = next((b for b in REWARD_BENEFITS_CATALOG if b["id"] == reward_id), None)
    if not benefit:
        err_msg = "Invalid reward benefit selected."
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": err_msg}), 400
        flash(err_msg, "error")
        return redirect(url_for("passenger.dashboard"))

    summary = get_passenger_rewards_summary(user["id"], db)
    if summary["available_points"] < benefit["points_cost"]:
        err_msg = f"Insufficient points balance ({summary['available_points']} pts available, need {benefit['points_cost']} pts)."
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": err_msg}), 400
        flash(err_msg, "error")
        return redirect(url_for("passenger.dashboard"))

    # Generate unique voucher code
    prefix = benefit["id"].split("_")[1].upper()[:4]
    random_hex = uuid.uuid4().hex[:4].upper()
    voucher_code = f"RW-{prefix}-{random_hex}"
    redemption_id = f"red_{uuid.uuid4().hex[:10]}"

    db.execute(
        """INSERT INTO rewards_redemptions
        (id, passenger_id, reward_id, reward_title, points_spent, voucher_code, discount_ugx, status, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', CURRENT_TIMESTAMP, datetime('now', '+60 days'))""",
        (redemption_id, user["id"], benefit["id"], benefit["title"], benefit["points_cost"], voucher_code, benefit["discount_ugx"])
    )

    # In-app notification
    NotificationService.create_notification(
        user_id=user["id"],
        title="Reward Redeemed Successfully",
        message=f"You redeemed '{benefit['title']}'. Voucher Code: {voucher_code} (Valid for 60 days).",
        notif_type="SYSTEM",
        related_entity_id=redemption_id
    )

    # Recompute updated summary
    updated_summary = get_passenger_rewards_summary(user["id"], db)

    voucher_data = {
        "id": redemption_id,
        "title": benefit["title"],
        "voucher_code": voucher_code,
        "points_spent": benefit["points_cost"],
        "discount_ugx": benefit["discount_ugx"],
        "status": "ACTIVE",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "expires_at": (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
    }

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "message": f"Successfully redeemed '{benefit['title']}'! Your voucher code is {voucher_code}.",
            "voucher": voucher_data,
            "rewards": updated_summary
        })

    flash(f"Perk redeemed! Voucher code: {voucher_code}", "success")
    return redirect(url_for("passenger.dashboard"))

@passenger_bp.route("/rewards/api/summary")
def api_rewards_summary():
    """Real-time JSON endpoint for passenger rewards summary."""
    user = AuthService.get_current_user()
    db = get_db()
    summary = get_passenger_rewards_summary(user["id"], db)
    return jsonify({
        "success": True,
        "rewards": summary
    })

@passenger_bp.route("/book-ride", methods=["GET", "POST"])
def book_ride():
    user = AuthService.get_current_user()
    db = get_db()
    landmarks = MapService.LANDMARKS

    if request.method == "POST":
        pickup_address = request.form.get("pickup_address", "").strip()
        destination_address = request.form.get("destination_address", "").strip()
        category = request.form.get("category", "ECONOMY").upper()
        payment_method = request.form.get("payment_method", "CASH").upper()
        is_airport = 1 if request.form.get("is_airport_ride") == "1" else 0
        related_journey_id = request.form.get("related_journey_id", "").strip() or None

        if not pickup_address or not destination_address:
            flash("Please provide both pickup and destination locations.", "error")
            return render_template("passenger/book_ride.html", user=user, landmarks=landmarks)

        # Coordinate lookup & distance calculation
        p_coords = MapService.find_coordinates(pickup_address)
        d_coords = MapService.find_coordinates(destination_address)

        # Haversine distance with road curvature
        distance_km = MapService.calculate_distance_km(
            p_coords["lat"], p_coords["lng"], d_coords["lat"], d_coords["lng"]
        )
        if distance_km < 1.0:
            distance_km = 3.5  # Sensible minimum for city transfers

        estimated_fare = PricingService.calculate_fare(category, distance_km)

        # Find available online verified driver
        available_driver = db.fetchone(
            """SELECT d.user_id, u.full_name, v.plate_number, v.make, v.model
            FROM driver_profiles d
            JOIN users u ON d.user_id = u.id
            JOIN vehicles v ON v.driver_id = u.id
            WHERE d.is_online = 1 AND d.verification_status = 'APPROVED'
            LIMIT 1"""
        )

        ride_id = f"ride_{uuid.uuid4().hex[:10]}"
        driver_id = available_driver["user_id"] if available_driver else None
        status = "DRIVER_ASSIGNED" if driver_id else "SEARCHING_FOR_DRIVER"

        db.execute(
            """INSERT INTO rides 
            (id, passenger_id, driver_id, category, pickup_address, pickup_lat, pickup_lng, 
             destination_address, destination_lat, destination_lng, estimated_distance_km, 
             estimated_fare_ugx, final_fare_ugx, payment_method, payment_status, status, is_airport_ride, related_journey_id) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'UNPAID', ?, ?, ?)""",
            (ride_id, user["id"], driver_id, category, pickup_address, p_coords["lat"], p_coords["lng"],
             destination_address, d_coords["lat"], d_coords["lng"], distance_km,
             estimated_fare, estimated_fare, payment_method, status, is_airport, related_journey_id)
        )

        if related_journey_id:
            db.execute("UPDATE confirmed_journeys SET airport_ride_booked = 1 WHERE id = ?", (related_journey_id,))

        # In-App Notification: Notify passenger when driver is assigned
        if driver_id and available_driver:
            NotificationService.create_notification(
                user_id=user["id"],
                title="Driver Assigned",
                message=f"{available_driver['full_name']} ({available_driver['plate_number']} {available_driver['make']} {available_driver['model']}) has been assigned to your ride #{ride_id[:8].upper()} and is en route.",
                notif_type="DRIVER_ASSIGNED",
                related_entity_id=ride_id
            )

        flash(f"Ride requested successfully! Assigned reference: #{ride_id[:8].upper()}", "success")
        return redirect(url_for("passenger.ride_detail", ride_id=ride_id))

    # Pre-filled params from Airport link or Repeat Ride link
    pre_pickup = request.args.get("pickup", "")
    pre_destination = request.args.get("destination", "")
    pre_category = request.args.get("category", "ECONOMY").upper()
    is_airport = request.args.get("is_airport", "0")
    journey_id = request.args.get("journey_id", "")

    # Fetch passenger saved routes for quick access
    saved_routes = db.fetchall(
        "SELECT * FROM saved_routes WHERE passenger_id = ? ORDER BY created_at DESC",
        (user["id"],)
    )

    return render_template(
        "passenger/book_ride.html",
        user=user,
        landmarks=landmarks,
        saved_routes=saved_routes,
        pre_pickup=pre_pickup,
        pre_destination=pre_destination,
        pre_category=pre_category,
        is_airport=is_airport,
        journey_id=journey_id
    )

@passenger_bp.route("/saved-routes", methods=["GET", "POST"])
def saved_routes():
    """Manages frequent passenger travel routes for quick 1-click booking."""
    user = AuthService.get_current_user()
    db = get_db()

    if request.method == "POST":
        data = request.get_json(silent=True) or request.form
        name = data.get("name", "").strip()
        pickup_address = data.get("pickup_address", "").strip()
        destination_address = data.get("destination_address", "").strip()
        category = data.get("category", "ECONOMY").upper()

        if not name or not pickup_address or not destination_address:
            err_msg = "Please provide route name, pickup location, and destination."
            if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return jsonify({"success": False, "error": err_msg}), 400
            flash(err_msg, "error")
            return redirect(url_for("passenger.book_ride"))

        route_id = f"rt_{uuid.uuid4().hex[:10]}"
        db.execute(
            """INSERT INTO saved_routes (id, passenger_id, name, pickup_address, destination_address, category)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (route_id, user["id"], name, pickup_address, destination_address, category)
        )

        route_record = {
            "id": route_id,
            "passenger_id": user["id"],
            "name": name,
            "pickup_address": pickup_address,
            "destination_address": destination_address,
            "category": category
        }

        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": True, "route": route_record})

        flash(f"Route '{name}' saved to your frequent routes!", "success")
        return redirect(url_for("passenger.book_ride"))

    routes = db.fetchall(
        "SELECT * FROM saved_routes WHERE passenger_id = ? ORDER BY created_at DESC",
        (user["id"],)
    )
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "saved_routes": routes})
    return redirect(url_for("passenger.book_ride"))

@passenger_bp.route("/saved-routes/<route_id>/delete", methods=["POST"])
def delete_saved_route(route_id):
    """Deletes a saved route."""
    user = AuthService.get_current_user()
    db = get_db()

    route = db.fetchone(
        "SELECT * FROM saved_routes WHERE id = ? AND passenger_id = ?",
        (route_id, user["id"])
    )
    if not route:
        if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"success": False, "error": "Route not found"}), 404
        abort(404)

    db.execute("DELETE FROM saved_routes WHERE id = ? AND passenger_id = ?", (route_id, user["id"]))

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"success": True, "id": route_id})

    flash(f"Route '{route['name']}' removed from your saved routes.", "info")
    return redirect(url_for("passenger.book_ride"))

@passenger_bp.route("/rides")
def rides_list():
    user = AuthService.get_current_user()
    db = get_db()
    rides = db.fetchall(
        """SELECT r.*, u.full_name as driver_name, u.phone as driver_phone, v.plate_number, v.make, v.model
        FROM rides r
        LEFT JOIN users u ON r.driver_id = u.id
        LEFT JOIN vehicles v ON v.driver_id = u.id
        WHERE r.passenger_id = ?
        ORDER BY r.created_at DESC""",
        (user["id"],)
    )
    return render_template("passenger/rides.html", user=user, rides=rides)

@passenger_bp.route("/rides/<ride_id>")
def ride_detail(ride_id):
    user = AuthService.get_current_user()
    db = get_db()
    ride = db.fetchone(
        """SELECT r.*, u.full_name as driver_name, u.phone as driver_phone, 
                  d.rating_avg as driver_rating, v.plate_number, v.make, v.model, v.color
        FROM rides r
        LEFT JOIN users u ON r.driver_id = u.id
        LEFT JOIN driver_profiles d ON d.user_id = u.id
        LEFT JOIN vehicles v ON v.driver_id = u.id
        WHERE r.id = ? AND r.passenger_id = ?""",
        (ride_id, user["id"])
    )
    if not ride:
        abort(404)
    return render_template("passenger/ride_detail.html", user=user, ride=ride)

@passenger_bp.route("/rides/<ride_id>/cancel", methods=["GET", "POST"])
def cancel_ride(ride_id):
    user = AuthService.get_current_user()
    db = get_db()
    ride = db.fetchone(
        """SELECT r.*, u.full_name as driver_name, u.phone as driver_phone,
                  v.plate_number, v.make, v.model
        FROM rides r
        LEFT JOIN users u ON r.driver_id = u.id
        LEFT JOIN vehicles v ON v.driver_id = u.id
        WHERE r.id = ? AND r.passenger_id = ?""",
        (ride_id, user["id"])
    )
    if not ride:
        abort(404)

    # Check if driver has already been assigned
    is_driver_assigned = bool(ride["driver_id"] or ride["status"] not in ("REQUESTED", "SEARCHING_FOR_DRIVER"))

    if request.method == "POST":
        if is_driver_assigned:
            flash("Under RideEasy cancellation rules, direct cancellation is locked once a driver has been dispatched. Please contact support or your driver.", "error")
            return redirect(url_for("passenger.ride_detail", ride_id=ride_id))

        if ride["status"] == "CANCELLED":
            flash("This ride has already been cancelled.", "info")
            return redirect(url_for("passenger.ride_detail", ride_id=ride_id))

        reason = request.form.get("reason", "Cancelled by passenger before driver assignment").strip()
        custom_notes = request.form.get("custom_notes", "").strip()
        full_reason = f"{reason} — {custom_notes}" if custom_notes else reason

        db.execute(
            """UPDATE rides 
            SET status = 'CANCELLED', cancellation_reason = ?, cancelled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP 
            WHERE id = ?""",
            (full_reason, ride_id)
        )

        # Audit log entry
        db.execute(
            "INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details) VALUES (?, ?, ?, ?, ?, ?)",
            (f"aud_{uuid.uuid4().hex[:8]}", user["id"], "PASSENGER_CANCELLED_RIDE", "RIDE", ride_id, f"Reason: {full_reason}")
        )

        # In-app notification to passenger
        NotificationService.create_notification(
            user_id=user["id"],
            title="Ride Request Cancelled",
            message=f"Your ride request #{ride_id[:8].upper()} was cancelled successfully before driver assignment.",
            notif_type="CANCELLATION",
            related_entity_id=ride_id
        )

        flash(f"Ride request #{ride_id[:8].upper()} has been cancelled and logged in your ride history.", "info")
        return redirect(url_for("passenger.rides_list"))

    # GET request displays the confirmation step with clear cancellation rules
    return render_template("passenger/cancel_confirm.html", user=user, ride=ride, is_driver_assigned=is_driver_assigned)

@passenger_bp.route("/rides/<ride_id>/rate", methods=["POST"])
def rate_ride(ride_id):
    user = AuthService.get_current_user()
    db = get_db()
    ride = db.fetchone("SELECT * FROM rides WHERE id = ? AND passenger_id = ?", (ride_id, user["id"]))
    if not ride or not ride["driver_id"]:
        abort(404)

    data = request.get_json(silent=True) or request.form
    try:
        rating = int(data.get("rating", 5))
    except (ValueError, TypeError):
        rating = 5
    rating = max(1, min(5, rating))
    review = (data.get("review") or "").strip()

    rating_id = f"rat_{uuid.uuid4().hex[:10]}"
    db.execute(
        "INSERT OR REPLACE INTO ride_ratings (id, ride_id, passenger_id, driver_id, rating, review) VALUES (?, ?, ?, ?, ?, ?)",
        (rating_id, ride_id, user["id"], ride["driver_id"], rating, review)
    )

    # Update driver average rating
    driver_stats = db.fetchone(
        "SELECT AVG(rating) as avg_r, COUNT(*) as cnt FROM ride_ratings WHERE driver_id = ?",
        (ride["driver_id"],)
    )
    if driver_stats and driver_stats["cnt"]:
        db.execute(
            "UPDATE driver_profiles SET rating_avg = ?, rating_count = ? WHERE user_id = ?",
            (round(driver_stats["avg_r"], 1), driver_stats["cnt"], ride["driver_id"])
        )

    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({
            "success": True,
            "status": "success",
            "ride_id": ride_id,
            "rating": rating,
            "review": review,
            "message": f"Trip rated {rating} star{'s' if rating != 1 else ''}! Feedback saved."
        })

    flash("Thank you for rating your trip.", "success")
    next_url = request.form.get("next") or request.referrer or url_for("passenger.dashboard")
    return redirect(next_url)

@passenger_bp.route("/rides/<ride_id>/receipt")
def receipt(ride_id):
    user = AuthService.get_current_user()
    db = get_db()
    ride = db.fetchone("SELECT * FROM rides WHERE id = ? AND passenger_id = ?", (ride_id, user["id"]))
    if not ride:
        abort(404)

    driver = None
    if ride["driver_id"]:
        driver = db.fetchone(
            """SELECT u.full_name, v.plate_number, v.make, v.model 
            FROM users u LEFT JOIN vehicles v ON v.driver_id = u.id 
            WHERE u.id = ?""",
            (ride["driver_id"],)
        )

    receipt_data = PaymentService.generate_receipt_data(ride, user, driver)
    return render_template("passenger/receipt.html", user=user, receipt=receipt_data, ride=ride)

@passenger_bp.route("/flight-request", methods=["GET", "POST"])
def flight_request():
    user = AuthService.get_current_user()
    db = get_db()

    if request.method == "POST":
        dep_city = request.form.get("departure_city", "").strip()
        dest_city = request.form.get("destination_city", "").strip()
        dep_date = request.form.get("departure_date", "").strip()
        ret_date = request.form.get("return_date", "").strip() or None
        passengers = int(request.form.get("passenger_count", 1))
        airline = request.form.get("preferred_airline", "").strip()
        cabin = request.form.get("cabin_class", "Economy")
        phone = request.form.get("phone", user["phone"]).strip()
        email = request.form.get("email", user["email"]).strip()
        preferences = request.form.get("travel_preferences", "").strip()
        notes = request.form.get("notes", "").strip()

        # Find verified travel partner to assign
        partner = db.fetchone(
            "SELECT user_id FROM travel_companies WHERE verification_status = 'APPROVED' LIMIT 1"
        )
        assigned_company_id = partner["user_id"] if partner else None

        req_id = f"flt_req_{uuid.uuid4().hex[:10]}"
        db.execute(
            """INSERT INTO flight_requests 
            (id, passenger_id, departure_city, destination_city, departure_date, return_date, 
             passenger_count, preferred_airline, cabin_class, phone, email, travel_preferences, notes, 
             assigned_company_id, status) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'SUBMITTED')""",
            (req_id, user["id"], dep_city, dest_city, dep_date, ret_date,
             passengers, airline, cabin, phone, email, preferences, notes, assigned_company_id)
        )

        flash("Your flight booking inquiry has been submitted. A verified IATA travel partner will contact you with verified flight options.", "success")
        return redirect(url_for("passenger.flight_request_detail", request_id=req_id))

    return render_template("passenger/flight_request.html", user=user)

@passenger_bp.route("/flight-requests/<request_id>")
def flight_request_detail(request_id):
    user = AuthService.get_current_user()
    db = get_db()
    req_item = db.fetchone(
        """SELECT r.*, c.company_name, c.contact_person, c.phone as company_phone, c.email as company_email
        FROM flight_requests r
        LEFT JOIN travel_companies c ON r.assigned_company_id = c.user_id
        WHERE r.id = ? AND r.passenger_id = ?""",
        (request_id, user["id"])
    )
    if not req_item:
        abort(404)

    quotations = db.fetchall(
        "SELECT * FROM flight_quotations WHERE request_id = ? ORDER BY created_at DESC",
        (request_id,)
    )

    booking = db.fetchone(
        "SELECT * FROM flight_bookings WHERE request_id = ?",
        (request_id,)
    )

    return render_template("passenger/flight_request_detail.html", user=user, req=req_item, quotations=quotations, booking=booking)

@passenger_bp.route("/quotations/<quote_id>/accept", methods=["POST"])
def accept_quotation(quote_id):
    user = AuthService.get_current_user()
    db = get_db()
    quote = db.fetchone(
        """SELECT q.*, r.passenger_id, r.id as req_id 
        FROM flight_quotations q 
        JOIN flight_requests r ON q.request_id = r.id 
        WHERE q.id = ? AND r.passenger_id = ?""",
        (quote_id, user["id"])
    )
    if not quote:
        abort(404)

    db.execute("UPDATE flight_quotations SET status = 'ACCEPTED' WHERE id = ?", (quote_id,))
    db.execute("UPDATE flight_requests SET status = 'CUSTOMER_APPROVED' WHERE id = ?", (quote["req_id"],))

    flash("Quotation accepted! The verified travel partner has been notified to issue the confirmed ticket and PNR.", "success")
    return redirect(url_for("passenger.flight_request_detail", request_id=quote["req_id"]))

@passenger_bp.route("/journeys")
def journeys():
    user = AuthService.get_current_user()
    db = get_db()
    journeys_list = db.fetchall(
        """SELECT j.*, b.booking_reference_pnr, b.airline_name, b.flight_number, b.airline_ticket_number
        FROM confirmed_journeys j
        JOIN flight_bookings b ON j.flight_booking_id = b.id
        WHERE j.passenger_id = ?
        ORDER BY j.departure_datetime ASC""",
        (user["id"],)
    )

    # Fetch reminders for each journey
    reminders = db.fetchall(
        """SELECT r.*, j.destination 
        FROM journey_reminders r
        JOIN confirmed_journeys j ON r.journey_id = j.id
        WHERE j.passenger_id = ?
        ORDER BY r.scheduled_for ASC""",
        (user["id"],)
    )

    return render_template("passenger/journeys.html", user=user, journeys=journeys_list, reminders=reminders)
