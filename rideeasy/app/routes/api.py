from flask import Blueprint, current_app, jsonify, request
from app.repositories.database import get_db
from app.services.pricing_service import MapService, PricingService
from app.services.auth_service import login_required, role_required
from app.services.location_service import (
    LocationIQConfigurationError,
    LocationIQNoResultsError,
    LocationIQRequestError,
    LocationService,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")

@api_bp.route("/estimate-fare", methods=["POST"])
def estimate_fare():
    """Calculates live fare estimate between two locations."""
    data = request.get_json() or {}
    pickup = data.get("pickup", "").strip()
    destination = data.get("destination", "").strip()
    category = data.get("category", "ECONOMY").upper()

    if not pickup or not destination:
        return jsonify({"error": "Pickup and destination required"}), 400

    p_coords = MapService.find_coordinates(pickup)
    d_coords = MapService.find_coordinates(destination)
    distance_km = MapService.calculate_distance_km(p_coords["lat"], p_coords["lng"], d_coords["lat"], d_coords["lng"])
    if distance_km < 1.0:
        distance_km = 3.5

    fare = PricingService.calculate_fare(category, distance_km)

    return jsonify({
        "success": True,
        "category": category,
        "distance_km": distance_km,
        "estimated_fare_ugx": fare,
        "pickup_coords": p_coords,
        "destination_coords": d_coords,
        "currency": "UGX"
    })

@api_bp.route("/landmarks")
def landmarks():
    return jsonify({"landmarks": MapService.LANDMARKS})

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
        route = LocationService.get_route(start, destination)
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
def ride_status(ride_id):
    db = get_db()
    ride = db.fetchone(
        """SELECT r.id, r.status, r.driver_id, r.driver_response_status,
                  r.estimated_fare_ugx, r.final_fare_ugx, r.payment_status,
                  u.full_name as driver_name, u.phone as driver_phone,
                  v.plate_number, v.make, v.model, v.color
        FROM rides r
        LEFT JOIN users u ON r.driver_id = u.id
        LEFT JOIN vehicles v ON v.driver_id = u.id
        WHERE r.id = ?""",
        (ride_id,)
    )
    if not ride:
        return jsonify({"error": "Ride not found"}), 404
    return jsonify({"success": True, "ride": ride})

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
