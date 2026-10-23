def test_school_can_request_coaster_charter(client):
    client.get("/auth/demo/school", follow_redirects=True)
    assert b"School Safety & Compliance" in client.get("/school/dashboard").data
    assert b"Transport Requests" in client.get("/school/requests").data
    response = client.post("/school/request", data={
        "vehicle_type": "COASTER",
        "passenger_count": "28",
        "pickup_location": "Greenhill Academy Kibuli Campus",
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

def test_parents_cannot_access_school_booking_directly(client):
    # Log in as passenger
    client.get("/auth/demo/passenger", follow_redirects=True)
    # Attempting to access school booking should return 403 Forbidden
    response = client.get("/school/request")
    assert response.status_code == 403
