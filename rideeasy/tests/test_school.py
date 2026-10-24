import uuid


def test_school_can_request_coaster_charter(client, db, monkeypatch):
    client.get("/auth/demo/school", follow_redirects=True)
    monkeypatch.setattr("app.routes.school.LocationService.get_route", lambda *args, **kwargs: {
        "start": {"lat": 0.306, "lng": 32.598, "label": "Kibuli, Uganda"},
        "destination": {"lat": 0.43, "lng": 33.2, "label": "Jinja, Uganda"},
        "distance_km": 82.4,
        "duration_minutes": 115,
    })
    assert b"School Safety & Compliance" in client.get("/school/dashboard").data
    assert b"Transport Requests" in client.get("/school/requests").data
    pickup_location = f"Test campus {uuid.uuid4().hex}"
    response = client.post("/school/request", data={
        "vehicle_type": "COASTER",
        "passenger_count": "28",
        "pickup_location": pickup_location,
        "destination": "Jinja Source of the Nile",
        "travel_date": "2026-11-20",
        "departure_time": "07:30 AM",
        "return_date": "2026-11-20",
        "return_time": "05:00 PM",
        "special_requirements": "First aid box and luggage compartment for band equipment."
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Transport request submitted successfully" in response.data
    assert b"Jinja Source of the Nile" in response.data
    request_row = db.fetchone(
        "SELECT agreed_price_ugx FROM school_transport_requests WHERE pickup_location = ?",
        (pickup_location,),
    )
    from app.services.pricing_service import PricingService
    assert request_row["agreed_price_ugx"] == PricingService.calculate_fare("COASTER", 164.8, 230)

def test_parents_cannot_access_school_booking_directly(client):
    # Log in as passenger
    client.get("/auth/demo/passenger", follow_redirects=True)
    # Attempting to access school booking should return 403 Forbidden
    response = client.get("/school/request")
    assert response.status_code == 403
