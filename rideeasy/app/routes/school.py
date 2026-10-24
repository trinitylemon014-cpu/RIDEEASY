import uuid
from flask import Blueprint, current_app, render_template, request, redirect, url_for, flash, session, abort
from app.repositories.database import get_db
from app.services.auth_service import login_required, role_required, AuthService
from app.services.location_service import (
    LocationIQConfigurationError,
    LocationIQNoResultsError,
    LocationIQRequestError,
    LocationService,
)
from app.services.pricing_service import PricingService

school_bp = Blueprint("school", __name__, url_prefix="/school")

@school_bp.before_request
@login_required
@role_required("SCHOOL", "ADMIN")
def before_request():
    pass

def get_school_requests(school_id):
    return get_db().fetchall(
        """SELECT r.*, u.full_name as driver_name, u.avatar_url as driver_avatar_url,
                  u.phone as driver_phone,
                  v.plate_number, v.make, v.model, v.category as vehicle_category
        FROM school_transport_requests r
        LEFT JOIN users u ON r.assigned_driver_id = u.id
        LEFT JOIN vehicles v ON r.assigned_vehicle_id = v.id
        WHERE r.school_id = ?
        ORDER BY r.created_at DESC""",
        (school_id,)
    )

@school_bp.route("/dashboard")
def dashboard():
    user = AuthService.get_current_user()
    db = get_db()

    school = db.fetchone("SELECT * FROM schools WHERE user_id = ?", (user["id"],))
    requests = get_school_requests(user["id"])
    return render_template(
        "school/dashboard.html",
        user=user,
        school=school,
        requests=requests,
        recent_requests=requests[:3]
    )

@school_bp.route("/requests")
def requests_list():
    user = AuthService.get_current_user()
    return render_template(
        "school/requests.html",
        user=user,
        school=get_db().fetchone("SELECT * FROM schools WHERE user_id = ?", (user["id"],)),
        requests=get_school_requests(user["id"])
    )

@school_bp.route("/request", methods=["GET", "POST"])
def new_request():
    user = AuthService.get_current_user()
    db = get_db()
    school = db.fetchone("SELECT * FROM schools WHERE user_id = ?", (user["id"],))
    pickup_location = request.args.get("pickup", "").strip() or (school["address"] if school else "")
    destination = request.args.get("destination", "").strip()

    if request.method == "POST":
        vehicle_type = request.form.get("vehicle_type", "COASTER").upper()
        passenger_count = int(request.form.get("passenger_count", 25))
        pickup_location = request.form.get("pickup_location", "").strip()
        destination = request.form.get("destination", "").strip()
        travel_date = request.form.get("travel_date", "").strip()
        departure_time = request.form.get("departure_time", "").strip()
        return_date = request.form.get("return_date", "").strip() or None
        return_time = request.form.get("return_time", "").strip() or None
        special_reqs = request.form.get("special_requirements", "").strip()

        if not pickup_location or not destination or not travel_date or not departure_time:
            flash("Pickup, destination, travel date, and departure time are required.", "error")
            return render_template(
                "school/request.html",
                user=user,
                school=school,
                pickup_location=pickup_location,
                destination=destination
            )
        if len(pickup_location) > 300 or len(destination) > 300:
            flash("Pickup and destination locations must be 300 characters or fewer.", "error")
            return render_template(
                "school/request.html",
                user=user,
                school=school,
                pickup_location=pickup_location,
                destination=destination
            )
        if pickup_location.casefold() == destination.casefold():
            flash("Choose two different locations for pickup and destination.", "error")
            return render_template(
                "school/request.html",
                user=user,
                school=school,
                pickup_location=pickup_location,
                destination=destination
            )

        if vehicle_type not in {"COASTER", "BUS"}:
            flash("Please choose a valid school vehicle type.", "error")
            return render_template(
                "school/request.html",
                user=user,
                school=school,
                pickup_location=pickup_location,
                destination=destination
            )
        try:
            route = LocationService.get_route(pickup_location, destination)
        except LocationIQConfigurationError:
            flash("School transport pricing is temporarily unavailable. Please try again later.", "error")
            return render_template(
                "school/request.html",
                user=user,
                school=school,
                pickup_location=pickup_location,
                destination=destination
            )
        except LocationIQNoResultsError as error:
            flash(str(error), "error")
            return render_template(
                "school/request.html",
                user=user,
                school=school,
                pickup_location=pickup_location,
                destination=destination
            )
        except LocationIQRequestError as error:
            current_app.logger.warning("School charter route unavailable: %s", error)
            flash("We could not verify the road route. No transport request was submitted.", "error")
            return render_template(
                "school/request.html",
                user=user,
                school=school,
                pickup_location=pickup_location,
                destination=destination
            )

        dist = route["distance_km"]
        duration_minutes = route["duration_minutes"]
        if return_date:
            dist *= 2
            duration_minutes *= 2

        estimated_price = PricingService.calculate_fare(vehicle_type, dist, duration_minutes)

        req_id = f"sch_req_{uuid.uuid4().hex[:10]}"
        db.execute(
            """INSERT INTO school_transport_requests 
            (id, school_id, vehicle_type, passenger_count, pickup_location, destination, 
             travel_date, departure_time, return_date, return_time, special_requirements, 
             status, agreed_price_ugx, invoice_status) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, 'PENDING')""",
            (req_id, user["id"], vehicle_type, passenger_count, pickup_location, destination,
             travel_date, departure_time, return_date, return_time, special_reqs, estimated_price)
        )

        flash("Transport request submitted successfully! RideEasy operations team will review and assign a certified driver and inspected vehicle.", "success")
        return redirect(url_for("school.dashboard"))

    return render_template(
        "school/request.html",
        user=user,
        school=school,
        pickup_location=pickup_location,
        destination=destination
    )

@school_bp.route("/requests/<request_id>")
def request_detail(request_id):
    user = AuthService.get_current_user()
    db = get_db()
    req_item = db.fetchone(
        """SELECT r.*, u.full_name as driver_name, u.avatar_url as driver_avatar_url,
                  u.phone as driver_phone,
                  v.plate_number, v.make, v.model, v.capacity as vehicle_capacity,
                  s.school_name, s.contact_person, s.phone as school_phone
        FROM school_transport_requests r
        JOIN schools s ON r.school_id = s.user_id
        LEFT JOIN users u ON r.assigned_driver_id = u.id
        LEFT JOIN vehicles v ON r.assigned_vehicle_id = v.id
        WHERE r.id = ? AND (r.school_id = ? OR ? = 'ADMIN')""",
        (request_id, user["id"], user["role"])
    )
    if not req_item:
        abort(404)
    return render_template("school/request_detail.html", user=user, req=req_item)
