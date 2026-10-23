from app.services.pricing_service import MapService, PricingService

def test_fare_calculation_formula():
    # 10 km in Economy (3500 base + 1500*10 + min wait)
    fare = PricingService.calculate_fare("ECONOMY", 10.0)
    assert fare >= 18500
    assert fare % 500 == 0  # Tariff rounded to 500 UGX

def test_haversine_distance_calculation():
    # Acacia Mall Kololo to Entebbe Airport (~42 km)
    p_coords = MapService.find_coordinates("Acacia Mall, Kololo")
    d_coords = MapService.find_coordinates("Entebbe International Airport (EBB)")
    dist = MapService.calculate_distance_km(p_coords["lat"], p_coords["lng"], d_coords["lat"], d_coords["lng"])
    assert 35.0 <= dist <= 55.0

def test_passenger_can_request_ride(client):
    client.get("/auth/demo/passenger", follow_redirects=True)
    response = client.post("/passenger/book-ride", data={
        "pickup_address": "Acacia Mall, Kololo",
        "destination_address": "Entebbe International Airport (EBB)",
        "category": "ECONOMY",
        "payment_method": "MTN_MOMO",
        "is_airport_ride": "1",
        "related_journey_id": ""
    }, follow_redirects=True)
    assert response.status_code == 200
    assert b"Ride requested successfully" in response.data
    assert b"Trip #" in response.data

def test_api_fare_estimation(client):
    # Test valid fare estimation across categories
    res = client.post("/api/estimate-fare", json={
        "pickup": "Acacia Mall, Kisementi, Kololo",
        "destination": "Entebbe International Airport (EBB)",
        "category": "ECONOMY"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["distance_km"] > 35.0
    assert data["estimated_fare_ugx"] > 50000
    assert data["currency"] == "UGX"

    # Test Boda is cheaper than Economy
    boda_res = client.post("/api/estimate-fare", json={
        "pickup": "Acacia Mall, Kisementi, Kololo",
        "destination": "Entebbe International Airport (EBB)",
        "category": "BODA"
    })
    boda_data = boda_res.get_json()
    assert boda_data["estimated_fare_ugx"] < data["estimated_fare_ugx"]

    # Test missing fields error
    err_res = client.post("/api/estimate-fare", json={"pickup": ""})
    assert err_res.status_code == 400

def test_passenger_dashboard_shows_completed_rides_and_repeat_button(client):
    client.get("/auth/demo/passenger", follow_redirects=True)
    res = client.get("/passenger/dashboard")
    assert res.status_code == 200
    assert b"Recent Completed Rides" in res.data
    assert b"Request Repeat Ride" in res.data
    assert b"Fare Paid" in res.data
    assert b'id="ai-support-widget"' in res.data
    assert b'id="ai-support-panel"' in res.data
    assert b'id="ai-customer-care-section"' not in res.data

    # Test repeat ride link with pre-filled parameters
    repeat_res = client.get("/passenger/book-ride?pickup=Victoria+Towers%2C+Nakasero+Road&destination=Garden+City+Mall&category=COMFORT")
    assert repeat_res.status_code == 200
    assert b"Victoria Towers, Nakasero Road" in repeat_res.data
    assert b"Garden City Mall" in repeat_res.data
    assert b'value="COMFORT" checked' in repeat_res.data

def test_ai_customer_care_api(client, monkeypatch):
    from app.services.ai_support_service import AISupportService
    monkeypatch.setattr(AISupportService, "get_gemini_client", classmethod(lambda cls: None))

    # Test valid question about fares
    res = client.post("/api/support/chat", json={
        "message": "How are ride fares calculated in RideEasy?"
    })
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert "reply" in data
    assert len(data["reply"]) > 10
    assert data["model"] == "gemini-3.8-flash"

    # Test question about company
    comp_res = client.post("/api/support/chat", json={
        "message": "Tell me about Emtrixz Technology Company"
    })
    assert comp_res.status_code == 200
    comp_data = comp_res.get_json()
    assert comp_data["success"] is True
    assert "Emtrixz" in comp_data["reply"]

    # Test validation for empty message
    empty_res = client.post("/api/support/chat", json={"message": ""})
    assert empty_res.status_code == 400

def test_saved_routes_workflow(client):
    # 1. Login as passenger
    client.get("/auth/demo/passenger", follow_redirects=True)

    # 2. View book ride page, verify saved routes UI
    res = client.get("/passenger/book-ride")
    assert res.status_code == 200
    assert b"Saved Frequent Routes" in res.data
    assert b"Home to Office" in res.data
    assert b"Save This Route as Frequent" in res.data

    # 3. Save a new route via AJAX
    save_res = client.post("/passenger/saved-routes", json={
        "name": "Gym to Home",
        "pickup_address": "Lugogo Mall / Shoprite / Game",
        "destination_address": "Plot 14 Acacia Avenue, Kololo",
        "category": "COMFORT"
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert save_res.status_code == 200
    save_data = save_res.get_json()
    assert save_data["success"] is True
    assert save_data["route"]["name"] == "Gym to Home"
    route_id = save_data["route"]["id"]

    # 4. Verify route appears in saved routes list query
    list_res = client.get("/passenger/saved-routes", headers={"X-Requested-With": "XMLHttpRequest"})
    assert list_res.status_code == 200
    list_data = list_res.get_json()
    assert any(r["name"] == "Gym to Home" for r in list_data["saved_routes"])

    # 5. Delete the saved route
    del_res = client.post(f"/passenger/saved-routes/{route_id}/delete", headers={"X-Requested-With": "XMLHttpRequest"})
    assert del_res.status_code == 200
    del_data = del_res.get_json()
    assert del_data["success"] is True

    # 6. Test validation on empty save request
    invalid_res = client.post("/passenger/saved-routes", json={
        "name": "",
        "pickup_address": ""
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert invalid_res.status_code == 400

def test_rate_completed_ride_workflow(client):
    # 1. Login as passenger
    client.get("/auth/demo/passenger", follow_redirects=True)

    # 2. Rate completed ride_02 via AJAX
    rate_res = client.post("/passenger/rides/ride_02/rate", data={
        "rating": "5",
        "review": "Punctual and very smooth driving across Kampala!",
        "next": "/passenger/dashboard"
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert rate_res.status_code == 200
    rate_data = rate_res.get_json()
    assert rate_data["status"] == "success"
    assert rate_data["rating"] == 5
    assert "smooth driving" in rate_data["review"]

    # 3. Verify rating is persisted in database and dashboard
    dash_res = client.get("/passenger/dashboard")
    assert dash_res.status_code == 200
    assert b"5/5" in dash_res.data
    assert b"smooth driving across Kampala" in dash_res.data

    # 4. Update/edit the rating (e.g. adjust to 4 stars)
    update_res = client.post("/passenger/rides/ride_02/rate", data={
        "rating": "4",
        "review": "Updated review: very good driver overall",
        "next": "/passenger/dashboard"
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert update_res.status_code == 200
    upd_data = update_res.get_json()
    assert upd_data["rating"] == 4
    assert upd_data["review"] == "Updated review: very good driver overall"

    # 5. Verify clamping to 1-5
    clamp_res = client.post("/passenger/rides/ride_02/rate", data={
        "rating": "10",
        "review": "Over top rating"
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert clamp_res.status_code == 200
    assert clamp_res.get_json()["rating"] == 5

def test_dashboard_search_filtering(client):
    # Login as passenger
    client.get("/auth/demo/passenger", follow_redirects=True)

    # Test search with query parameter
    search_entebbe = client.get("/passenger/dashboard?q=Entebbe")
    assert search_entebbe.status_code == 200
    assert b"Entebbe International Airport" in search_entebbe.data
    assert b'value="Entebbe"' in search_entebbe.data

    # Test search with driver name
    search_driver = client.get("/passenger/dashboard?q=David")
    assert search_driver.status_code == 200
    assert b"David" in search_driver.data

    # Test search with no matching keyword
    search_none = client.get("/passenger/dashboard?q=NonExistentTown99")
    assert search_none.status_code == 200
    assert b"No completed rides on record matching" in search_none.data

def test_driver_weekly_earnings_summary(client):
    # 1. Login as driver
    client.get("/auth/demo/driver", follow_redirects=True)

    # 2. View driver console dashboard and verify earnings summary component
    dash_res = client.get("/driver/dashboard")
    assert dash_res.status_code == 200
    assert b"Real-Time Earnings Summary" in dash_res.data
    assert b"Financial Performance" in dash_res.data
    assert b"kpi-week-earnings" in dash_res.data
    assert b"svg-chart-mount" in dash_res.data
    assert b"Select Day to Inspect Individual Trips" in dash_res.data

    # 3. Query real-time earnings JSON API
    api_res = client.get("/driver/api/earnings-summary")
    assert api_res.status_code == 200
    data = api_res.get_json()
    assert data["success"] is True
    summary = data["summary"]
    assert "days" in summary
    assert len(summary["days"]) == 7  # Exactly past 7 rolling days
    assert summary["total_week_earnings"] > 0
    assert summary["total_week_trips"] > 0
    assert summary["avg_daily_earnings"] > 0
    assert summary["max_day_earnings"] > 0

    # 4. Verify each day has valid structure
    for day in summary["days"]:
        assert "date" in day
        assert "day_name" in day
        assert "label" in day
        assert "earnings_ugx" in day
        assert "trip_count" in day
        assert "is_today" in day

    # Verify the last day is marked as today
    assert summary["days"][-1]["is_today"] is True

def test_passenger_rewards_tracker_and_redemption(client):
    # 1. Login as passenger
    client.get("/auth/demo/passenger", follow_redirects=True)

    # 2. View passenger dashboard and check for rewards component
    dash_res = client.get("/passenger/dashboard")
    assert dash_res.status_code == 200
    assert b"RideEasy Rewards" in dash_res.data
    assert b"Available Points Balance" in dash_res.data
    assert b"Total Trip Distance" in dash_res.data
    assert b"Tier Progress" in dash_res.data
    assert b"Redeemable Travel Benefits" in dash_res.data

    # 3. Query rewards JSON API
    api_res = client.get("/passenger/rewards/api/summary")
    assert api_res.status_code == 200
    data = api_res.get_json()
    assert data["success"] is True
    rewards = data["rewards"]
    assert "total_km" in rewards
    assert rewards["total_km"] > 0
    assert rewards["total_earned_points"] > 0
    assert rewards["available_points"] > 0
    assert "tier_name" in rewards
    assert len(rewards["benefits"]) > 0

    initial_pts = rewards["available_points"]

    # 4. Redeem a valid benefit (UGX 5,000 Off City Ride - 350 pts)
    redeem_res = client.post("/passenger/rewards/redeem", json={
        "reward_id": "rew_city_discount_5k"
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert redeem_res.status_code == 200
    redeem_data = redeem_res.get_json()
    assert redeem_data["success"] is True
    assert "voucher" in redeem_data
    assert redeem_data["voucher"]["voucher_code"].startswith("RW-CITY-")
    assert redeem_data["rewards"]["available_points"] == initial_pts - 350

    # 5. Test invalid reward ID
    invalid_res = client.post("/passenger/rewards/redeem", json={
        "reward_id": "invalid_reward_xyz"
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert invalid_res.status_code == 400

    # 6. Test insufficient points
    over_res = client.post("/passenger/rewards/redeem", json={
        "reward_id": "rew_vip_lounge"
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    # If balance < 1800 pts, should fail with 400
    if redeem_data["rewards"]["available_points"] < 1800:
        assert over_res.status_code == 400
        assert "Insufficient points" in over_res.get_json()["error"]






