import math
import time
from collections import defaultdict, deque

from flask import Blueprint, Response, current_app, jsonify, request, session
from app.repositories.database import get_db
from app.services.driver_location_service import ACTIVE_TRIP_STATUSES, DriverLocationService
from app.services.push_service import PushService
from app.services.realtime_service import RealtimeService
from app.services.pricing_service import PricingService
from app.services.auth_service import AuthService, login_required, role_required
from app.services.location_service import (
    LocationIQConfigurationError,
    LocationIQNoResultsError,
    LocationIQRequestError,
    LocationService,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Light per-user throttle for the suggestion endpoint (LocationIQ plans are rate limited).
AUTOCOMPLETE_MAX_PER_MINUTE = 45
_autocomplete_hits = defaultdict(deque)
ESTIMATE_MAX_PER_MINUTE = 12
_estimate_hits = defaultdict(deque)
REVERSE_MAX_PER_MINUTE = 10
_reverse_hits = defaultdict(deque)
LOCATION_MAX_PER_MINUTE = 40
_location_hits = defaultdict(deque)
PUSH_MAX_PER_MINUTE = 10
_push_hits = defaultdict(deque)


def _same_origin_request() -> bool:
    """JSON POST endpoints require a custom header that other websites cannot send
    (browsers block it without a CORS preflight, which this app never grants)."""
    return request.headers.get("X-Requested-With") == "RideEasy"


def _rate_limited(hits_by_user, limit):
    who = session.get("user_id") or request.remote_addr or "anonymous"
    now = time.monotonic()
    hits = hits_by_user[who]
    while hits and now - hits[0] > 60:
        hits.popleft()
    if len(hits) >= limit:
        return True
    hits.append(now)
    return False


def _autocomplete_rate_limited():
    return _rate_limited(_autocomplete_hits, AUTOCOMPLETE_MAX_PER_MINUTE)


@api_bp.route("/estimate-fare", methods=["POST"])
def estimate_fare():
    """Estimate a fare from the LocationIQ driving route and configured tariffs."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "Enter a pickup and destination."}), 400

    pickup = data.get("pickup")
    destination = data.get("destination")
    category = data.get("category", "ECONOMY")
    if not isinstance(pickup, str) or not isinstance(destination, str):
        return jsonify({"success": False, "error": "Enter a pickup and destination."}), 400
    pickup = pickup.strip()
    destination = destination.strip()
    if not pickup or not destination:
        return jsonify({"success": False, "error": "Enter a pickup and destination."}), 400
    if len(pickup) > 300 or len(destination) > 300:
        return jsonify({"success": False, "error": "Locations must be 300 characters or fewer."}), 400
    if pickup.casefold() == destination.casefold():
        return jsonify({"success": False, "error": "Choose two different locations."}), 400
    if not isinstance(category, str) or category.upper() not in {
        "BODA", "ECONOMY", "COMFORT", "PREMIUM"
    }:
        return jsonify({"success": False, "error": "Choose a valid ride category."}), 400
    category = category.upper()
    if _rate_limited(_estimate_hits, ESTIMATE_MAX_PER_MINUTE):
        return jsonify({
            "success": False,
            "error": "Too many fare estimates. Please wait a minute and try again."
        }), 429

    try:
        # Resolve both text addresses server-side. Client coordinates and fares
        # are never authoritative, even for the preview quote.
        route = LocationService.get_route(pickup, destination)
        fare = PricingService.calculate_fare(
            category, route["distance_km"], route["duration_minutes"]
        )
    except LocationIQConfigurationError:
        return jsonify({
            "success": False,
            "error": "Fare estimates are unavailable until the administrator configures LOCATIONIQ_API_KEY."
        }), 503
    except LocationIQNoResultsError as error:
        return jsonify({"success": False, "error": str(error)}), 422
    except LocationIQRequestError as error:
        current_app.logger.warning("Fare estimate unavailable: %s", error)
        return jsonify({"success": False, "error": str(error)}), 502

    return jsonify({
        "success": True,
        "category": category,
        "distance_km": route["distance_km"],
        "duration_minutes": route["duration_minutes"],
        "estimated_fare_ugx": fare,
        "pickup_coords": route["start"],
        "destination_coords": route["destination"],
        "currency": "UGX"
    })

@api_bp.route("/places/autocomplete")
def places_autocomplete():
    """Place suggestions while the user types (Uganda first). Key stays server-side."""
    query = request.args.get("q", "")
    if not isinstance(query, str) or len(query.strip()) < LocationService.AUTOCOMPLETE_MIN_CHARS:
        return jsonify({"success": True, "suggestions": []})
    if _autocomplete_rate_limited():
        return jsonify({"success": False, "error": "Too many searches. Please slow down.", "suggestions": []}), 429
    try:
        suggestions = LocationService.autocomplete(query)
    except LocationIQConfigurationError:
        return jsonify({"success": False, "error": "Place search is not configured.", "suggestions": []}), 503
    except LocationIQRequestError:
        return jsonify({"success": False, "error": "Place search is unavailable.", "suggestions": []}), 502
    return jsonify({"success": True, "suggestions": suggestions})


@api_bp.route("/places/reverse")
@login_required
@role_required("PASSENGER", "DRIVER", "SCHOOL", "ADMIN")
def places_reverse():
    """Name the place at the user's device location (used by 'Use my current location')."""
    try:
        lat = float(request.args.get("lat", ""))
        lng = float(request.args.get("lng", ""))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "A valid location is required."}), 400
    if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
        return jsonify({"success": False, "error": "A valid location is required."}), 400
    if _rate_limited(_reverse_hits, REVERSE_MAX_PER_MINUTE):
        return jsonify({"success": False, "error": "Too many requests. Please wait a moment."}), 429
    try:
        place = LocationService.reverse_geocode(lat, lng)
    except LocationIQConfigurationError:
        return jsonify({"success": False, "error": "Place search is not configured."}), 503
    except LocationIQRequestError:
        return jsonify({"success": False, "error": "Place search is unavailable."}), 502
    return jsonify({"success": True, "place": place})


@api_bp.route("/route", methods=["POST"])
@login_required
@role_required("PASSENGER", "DRIVER", "SCHOOL", "ADMIN")
def calculate_route():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"success": False, "error": "Enter a start point and destination."}), 400
    start = data.get("start")
    destination = data.get("destination")
    if not isinstance(start, str) or not isinstance(destination, str):
        return jsonify({"success": False, "error": "Enter a start point and destination."}), 400

    start = start.strip()
    destination = destination.strip()
    if not start or not destination:
        return jsonify({"success": False, "error": "Enter a start point and destination."}), 400
    if len(start) > 300 or len(destination) > 300:
        return jsonify({"success": False, "error": "Locations must be 300 characters or fewer."}), 400
    if start.casefold() == destination.casefold():
        return jsonify({"success": False, "error": "Choose two different locations."}), 400

    try:
        route = LocationService.get_route(
            start,
            destination,
            start_point=data.get("start_point"),
            destination_point=data.get("destination_point"),
        )
    except LocationIQConfigurationError:
        return jsonify({
            "success": False,
            "error": "Route planning is not configured yet. Ask your administrator to set LOCATIONIQ_API_KEY."
        }), 503
    except LocationIQNoResultsError as error:
        return jsonify({"success": False, "error": str(error)}), 422
    except LocationIQRequestError as error:
        current_app.logger.warning("Route calculation unavailable: %s", error)
        return jsonify({"success": False, "error": str(error)}), 502

    return jsonify({"success": True, "route": route})

@api_bp.route("/ride-status/<ride_id>")
@login_required
@role_required("PASSENGER", "DRIVER", "ADMIN")
def ride_status(ride_id):
    db = get_db()
    ride_query = """SELECT r.id, r.passenger_id, r.status, r.driver_id, r.driver_response_status,
                  r.cancellation_reason,
                  r.estimated_distance_km, r.estimated_duration_minutes,
                  r.estimated_fare_ugx, r.final_fare_ugx, r.payment_status,
                  r.pickup_lat, r.pickup_lng, r.destination_lat, r.destination_lng,
                  r.pickup_eta_minutes, r.start_pin,
                  u.full_name as driver_name, u.phone as driver_phone,
                  u.avatar_url as driver_avatar_url,
                  v.plate_number, v.make, v.model, v.color
        FROM rides r
        LEFT JOIN users u ON r.driver_id = u.id
        LEFT JOIN vehicles v ON v.driver_id = u.id
        WHERE r.id = ?"""
    ride = db.fetchone(
        ride_query,
        (ride_id,)
    )
    if not ride:
        return jsonify({"error": "Ride not found"}), 404
    user = AuthService.get_current_user()
    if user["role"] != "ADMIN" and user["id"] not in {
        ride["passenger_id"], ride["driver_id"]
    }:
        return jsonify({"error": "Ride not found"}), 404
    from app.services.ride_dispatch_service import RideDispatchService
    RideDispatchService.expire_stale_offers(ride_id)
    RideDispatchService.expire_unmatched_rides(ride_id)
    ride = db.fetchone(ride_query, (ride_id,))
    if not ride or (
        user["role"] != "ADMIN"
        and user["id"] not in {ride["passenger_id"], ride["driver_id"]}
    ):
        return jsonify({"error": "Ride not found"}), 404

    payload = {key: value for key, value in ride.items() if key != "passenger_id"}
    # The start PIN is for the passenger only; the driver must ask for it.
    if user["id"] != ride["passenger_id"] or ride["status"] not in ACTIVE_TRIP_STATUSES:
        payload.pop("start_pin", None)

    payload["driver_location"] = None
    if (
        ride["driver_id"] and ride["driver_response_status"] == "ACCEPTED"
        and ride["status"] in ACTIVE_TRIP_STATUSES
    ):
        position = DriverLocationService.location_for_driver(
            ride["driver_id"], int(current_app.config.get("DISPATCH_LOCATION_MAX_AGE_SECONDS", 180)) * 2
        )
        if position:
            payload["driver_location"] = {
                "lat": position["lat"], "lng": position["lng"], "heading": position["heading"],
                "age_seconds": position["age_seconds"],
                **(DriverLocationService.progress(ride, position["lat"], position["lng"]) or {}),
            }
    return jsonify({"success": True, "ride": payload})


@api_bp.route("/stream")
@login_required
def stream():
    """Server-sent events: small 'something changed' hints and live driver positions."""
    user_id = session["user_id"]
    channel = RealtimeService.subscribe(user_id, max_total=int(current_app.config.get("REALTIME_MAX_STREAMS", 20)))
    if channel is None:
        busy = jsonify({"error": "Live updates are busy; falling back to periodic checks."})
        busy.status_code = 503
        busy.headers["Retry-After"] = "30"
        return busy
    generator = RealtimeService.event_stream(
        user_id, channel, max_seconds=int(current_app.config.get("REALTIME_STREAM_SECONDS", 55))
    )
    response = Response(generator, mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache, no-transform"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response


@api_bp.route("/driver/location", methods=["POST"])
@login_required
@role_required("DRIVER")
def driver_location():
    if not _same_origin_request():
        return jsonify({"error": "Invalid request."}), 400
    if _rate_limited(_location_hits, LOCATION_MAX_PER_MINUTE):
        return jsonify({"error": "Too many location updates."}), 429
    data = request.get_json(silent=True) or {}
    try:
        result = DriverLocationService.update(
            session["user_id"], data.get("lat"), data.get("lng"),
            heading=data.get("heading"), accuracy=data.get("accuracy"),
        )
    except ValueError:
        return jsonify({"error": "Invalid location."}), 400
    except LookupError:
        return jsonify({"error": "Driver profile not found."}), 404
    return jsonify(result)


@api_bp.route("/push/subscribe", methods=["POST"])
@login_required
def push_subscribe():
    if not _same_origin_request():
        return jsonify({"error": "Invalid request."}), 400
    if not PushService.enabled():
        return jsonify({"error": "Push notifications are not configured."}), 503
    if _rate_limited(_push_hits, PUSH_MAX_PER_MINUTE):
        return jsonify({"error": "Too many requests."}), 429
    subscription = request.get_json(silent=True) or {}
    if not PushService.save_subscription(session["user_id"], subscription):
        return jsonify({"error": "Invalid subscription."}), 400
    return jsonify({"success": True})


@api_bp.route("/push/unsubscribe", methods=["POST"])
@login_required
def push_unsubscribe():
    if not _same_origin_request():
        return jsonify({"error": "Invalid request."}), 400
    endpoint = str((request.get_json(silent=True) or {}).get("endpoint") or "")
    PushService.remove_subscription(session["user_id"], endpoint)
    return jsonify({"success": True})

@api_bp.route("/support/chat", methods=["POST"])
def support_chat():
    """AI Customer Service Care endpoint for RideEasy and Emtrixz Technology Company."""
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    history = data.get("history", [])

    if not message:
        return jsonify({"success": False, "error": "Question message is required"}), 400

    from app.services.ai_support_service import AISupportService
    result = AISupportService.generate_reply(message, history)
    return jsonify(result)
