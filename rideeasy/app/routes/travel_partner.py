import uuid
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, abort
from app.repositories.database import get_db
from app.services.auth_service import login_required, role_required, AuthService
from app.services.reminder_service import ReminderService

travel_bp = Blueprint("travel", __name__, url_prefix="/travel")

@travel_bp.before_request
@login_required
@role_required("TRAVEL_COMPANY", "ADMIN")
def before_request():
    pass

@travel_bp.route("/dashboard")
def dashboard():
    user = AuthService.get_current_user()
    db = get_db()

    company = db.fetchone("SELECT * FROM travel_companies WHERE user_id = ?", (user["id"],))

    # Assigned flight requests
    assigned_requests = db.fetchall(
        """SELECT r.*, u.full_name as passenger_name, u.phone as passenger_phone, u.email as passenger_email
        FROM flight_requests r
        JOIN users u ON r.passenger_id = u.id
        WHERE r.assigned_company_id = ?
        ORDER BY r.created_at DESC""",
        (user["id"],)
    )

    # Confirmed bookings recorded by this travel agency
    confirmed_bookings = db.fetchall(
        """SELECT b.*, r.departure_city, r.destination_city, u.full_name as passenger_name
        FROM flight_bookings b
        JOIN flight_requests r ON b.request_id = r.id
        JOIN users u ON r.passenger_id = u.id
        WHERE b.travel_company_id = ?
        ORDER BY b.created_at DESC""",
        (user["id"],)
    )

    return render_template(
        "travel_partner/dashboard.html",
        user=user,
        company=company,
        requests=assigned_requests,
        bookings=confirmed_bookings
    )

@travel_bp.route("/requests/<request_id>")
def request_detail(request_id):
    user = AuthService.get_current_user()
    db = get_db()
    req_item = db.fetchone(
        """SELECT r.*, u.full_name as passenger_name, u.phone as passenger_phone, u.email as passenger_email
        FROM flight_requests r
        JOIN users u ON r.passenger_id = u.id
        WHERE r.id = ? AND (r.assigned_company_id = ? OR ? = 'ADMIN')""",
        (request_id, user["id"], user["role"])
    )
    if not req_item:
        abort(404)

    quotations = db.fetchall("SELECT * FROM flight_quotations WHERE request_id = ?", (request_id,))
    booking = db.fetchone("SELECT * FROM flight_bookings WHERE request_id = ?", (request_id,))

    return render_template("travel_partner/request_detail.html", user=user, req=req_item, quotations=quotations, booking=booking)

@travel_bp.route("/requests/<request_id>/quote", methods=["POST"])
def submit_quotation(request_id):
    user = AuthService.get_current_user()
    db = get_db()

    proposed_airline = request.form.get("proposed_airline", "").strip()
    flight_number = request.form.get("flight_number", "").strip()
    departure_time = request.form.get("departure_time", "").strip()
    arrival_time = request.form.get("arrival_time", "").strip()
    itinerary_summary = request.form.get("itinerary_summary", "").strip()
    price_ugx = int(request.form.get("price_ugx", 0))
    valid_until = request.form.get("valid_until", "").strip()

    quote_id = f"quo_{uuid.uuid4().hex[:10]}"
    quote_ref = f"QUO-{uuid.uuid4().hex[:6].upper()}"

    db.execute(
        """INSERT INTO flight_quotations 
        (id, request_id, travel_company_id, quote_reference, proposed_airline, flight_number, 
         departure_time, arrival_time, itinerary_summary, price_ugx, valid_until, status) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')""",
        (quote_id, request_id, user["id"], quote_ref, proposed_airline, flight_number,
         departure_time, arrival_time, itinerary_summary, price_ugx, valid_until)
    )

    db.execute("UPDATE flight_requests SET status = 'QUOTED' WHERE id = ?", (request_id,))

    flash(f"Quotation {quote_ref} sent to customer for approval.", "success")
    return redirect(url_for("travel.request_detail", request_id=request_id))

@travel_bp.route("/requests/<request_id>/confirm-booking", methods=["POST"])
def confirm_booking(request_id):
    """
    Records genuine booking reference and PNR from the airline ticketing system,
    creating the confirmed journey and initiating automated travel reminders.
    """
    user = AuthService.get_current_user()
    db = get_db()

    req_item = db.fetchone("SELECT * FROM flight_requests WHERE id = ?", (request_id,))
    if not req_item:
        abort(404)

    pnr = request.form.get("booking_reference_pnr", "").strip().upper()
    ticket_num = request.form.get("airline_ticket_number", "").strip()
    airline = request.form.get("airline_name", "").strip()
    flight_num = request.form.get("flight_number", "").strip().upper()
    dep_airport = request.form.get("departure_airport", "").strip()
    arr_airport = request.form.get("arrival_airport", "").strip()
    dep_datetime = request.form.get("departure_datetime", "").strip()
    arr_datetime = request.form.get("arrival_datetime", "").strip() or None

    if not pnr or not airline or not flight_num or not dep_datetime:
        flash("PNR reference, airline name, flight number, and departure datetime are required.", "error")
        return redirect(url_for("travel.request_detail", request_id=request_id))

    booking_id = f"bk_{uuid.uuid4().hex[:10]}"
    journey_id = f"jrn_{uuid.uuid4().hex[:10]}"

    db.execute(
        """INSERT INTO flight_bookings 
        (id, request_id, travel_company_id, booking_reference_pnr, airline_ticket_number, 
         airline_name, flight_number, departure_airport, arrival_airport, departure_datetime, arrival_datetime, status) 
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'CONFIRMED')""",
        (booking_id, request_id, user["id"], pnr, ticket_num, airline, flight_num,
         dep_airport, arr_airport, dep_datetime, arr_datetime)
    )

    db.execute("UPDATE flight_requests SET status = 'CONFIRMED' WHERE id = ?", (request_id,))

    # Create Confirmed Journey for passenger
    db.execute(
        """INSERT INTO confirmed_journeys 
        (id, passenger_id, flight_booking_id, journey_type, departure_datetime, origin, destination, airport_ride_booked, status) 
        VALUES (?, ?, ?, 'OUTBOUND_FLIGHT', ?, ?, ?, 0, 'SCHEDULED')""",
        (journey_id, req_item["passenger_id"], booking_id, dep_datetime, dep_airport, arr_airport)
    )

    # Schedule 5-tier travel reminders
    ReminderService.schedule_journey_reminders(journey_id, dep_datetime, dep_airport, arr_airport)

    # Audit log
    db.execute(
        "INSERT INTO audit_logs (id, user_id, action, resource_type, resource_id, details) VALUES (?, ?, ?, ?, ?, ?)",
        (f"aud_{uuid.uuid4().hex[:8]}", user["id"], "CONFIRM_FLIGHT_BOOKING", "FLIGHT_BOOKING", booking_id, f"PNR: {pnr}, Ticket: {ticket_num}")
    )

    flash(f"Booking confirmed! PNR {pnr} registered. Automated 5-stage travel reminders scheduled for passenger.", "success")
    return redirect(url_for("travel.request_detail", request_id=request_id))
