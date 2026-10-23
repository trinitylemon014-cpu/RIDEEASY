def test_passenger_can_submit_flight_inquiry(client):
    client.get("/auth/demo/passenger", follow_redirects=True)
    response = client.post("/passenger/flight-request", data={
        "departure_city": "Entebbe (EBB)",
        "destination_city": "Nairobi (NBO)",
        "departure_date": "2026-11-25",
        "passenger_count": "1",
        "cabin_class": "Economy",
        "preferred_airline": "Uganda Airlines",
        "phone": "+256 772 123 456",
        "email": "passenger@rideeasy.ug",
        "travel_preferences": "Window seat, morning flight",
        "notes": "Business summit attendee"
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Your flight booking inquiry has been submitted" in response.data

def test_travel_company_can_quote_and_confirm_booking(client, db):
    # Log in as travel partner
    client.get("/auth/demo/travel", follow_redirects=True)

    # Fetch existing sample flight request assigned to this partner
    req = db.fetchone("SELECT id FROM flight_requests WHERE assigned_company_id = 'usr_travel_01'")
    if not req:
        # Assign if needed
        any_req = db.fetchone("SELECT id FROM flight_requests LIMIT 1")
        db.execute("UPDATE flight_requests SET assigned_company_id = 'usr_travel_01' WHERE id = ?", (any_req["id"],))
        req = any_req
    assert req is not None

    # Submit quotation
    res_quote = client.post(f"/travel/requests/{req['id']}/quote", data={
        "proposed_airline": "Uganda Airlines",
        "flight_number": "UR 446",
        "departure_time": "17:30 EAT",
        "arrival_time": "23:45 GST",
        "itinerary_summary": "Direct Entebbe to Dubai with 2x 23kg baggage.",
        "price_ugx": "2450000",
        "valid_until": "2026-11-05"
    }, follow_redirects=True)
    assert res_quote.status_code == 200

    # Confirm genuine PNR
    res_confirm = client.post(f"/travel/requests/{req['id']}/confirm-booking", data={
        "booking_reference_pnr": "EBB89K",
        "airline_ticket_number": "673-9821038472",
        "airline_name": "Uganda Airlines",
        "flight_number": "UR 446",
        "departure_airport": "Entebbe International Airport (EBB)",
        "arrival_airport": "Dubai International Airport (DXB)",
        "departure_datetime": "2026-11-15 17:30:00"
    }, follow_redirects=True)
    assert res_confirm.status_code == 200
    assert b"Booking confirmed! PNR EBB89K registered" in response_or_data(res_confirm)

    # Verify travel reminders were created for the confirmed journey
    reminders = db.fetchall(
        "SELECT * FROM journey_reminders WHERE message LIKE '%Dubai%' OR title LIKE '%Passport%'"
    )
    assert len(reminders) >= 1

def response_or_data(res):
    return res.data
