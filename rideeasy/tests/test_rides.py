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

def test_route_map_is_available_to_passenger_driver_and_school(client):
    for role, page_label in [
        ("passenger", b"Plan your journey"),
        ("driver", b"Plan your journey"),
        ("school", b"Plan your journey"),
    ]:
        response = client.get(f"/auth/demo/{role}", follow_redirects=True)
        assert response.status_code == 200
        map_response = client.get("/map")
        assert map_response.status_code == 200
        assert page_label in map_response.data
        assert b"route-map" in map_response.data
        assert b"Route Map" in map_response.data
        assert b'href="/map" class="btn btn-secondary btn-block">Route Map' in map_response.data
        alias_response = client.get("/maps")
        assert alias_response.status_code == 200

    client.get("/auth/demo/school", follow_redirects=True)
    school_map = client.get(
        "/map?pickup=Greenhill%20Academy%20Kibuli&destination=Jinja%20Source%20of%20the%20Nile"
    )
    assert b'value="Greenhill Academy Kibuli"' in school_map.data
    assert b'value="Jinja Source of the Nile"' in school_map.data
    school_booking = client.get(
        "/school/request?pickup=Greenhill%20Academy%20Kibuli&destination=Jinja%20Source%20of%20the%20Nile"
    )
    assert b'value="Greenhill Academy Kibuli"' in school_booking.data
    assert b'value="Jinja Source of the Nile"' in school_booking.data

    client.get("/auth/demo/travel", follow_redirects=True)
    travel_map = client.get("/map")
    assert travel_map.status_code == 200
    assert b"Back to travel partner dashboard" in travel_map.data

def test_route_api_reports_missing_configuration(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "")
    response = client.post("/api/route", json={
        "start": "Acacia Mall, Kampala",
        "destination": "Entebbe Airport",
    })
    assert response.status_code == 503
    assert "LOCATIONIQ_API_KEY" in response.get_json()["error"]

def test_map_uses_current_database_role_if_session_role_is_stale(client):
    client.get("/auth/demo/passenger", follow_redirects=True)
    with client.session_transaction() as session:
        session["user_role"] = "TRAVEL_COMPANY"

    response = client.get("/map")
    assert response.status_code == 200
    assert b"Back to ride booking" in response.data

def test_route_api_returns_locationiq_road_distance(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    requests_made = []

    class FakeResponse:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self.body

    def fake_get(url, params, timeout):
        requests_made.append((url, params, timeout))
        if url.endswith("/search"):
            latitude, longitude = (
                ("0.334", "32.589") if params["q"] == "Acacia Mall, Kampala"
                else ("0.0424", "32.4435")
            )
            return FakeResponse([{
                "lat": latitude,
                "lon": longitude,
                "display_name": f"{params['q']}, Uganda",
            }])
        return FakeResponse({
            "routes": [{
                "distance": 42100,
                "duration": 5400,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[32.589, 0.334], [32.4435, 0.0424]],
                },
            }]
        })

    monkeypatch.setattr("app.services.location_service.requests.get", fake_get)
    response = client.post("/api/route", json={
        "start": "Acacia Mall, Kampala",
        "destination": "Entebbe International Airport",
    })
    assert response.status_code == 200
    route = response.get_json()["route"]
    assert route["distance_km"] == 42.1
    assert route["duration_minutes"] == 90
    assert route["geometry"]["type"] == "LineString"
    assert len(requests_made) == 3
    assert all(call[1]["key"] == "test-locationiq-key" for call in requests_made)

    map_page = client.get("/map")
    assert b"test-locationiq-key" not in map_page.data

def test_route_api_validates_addresses_and_empty_provider_results(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    same_location = client.post("/api/route", json={"start": "Kampala", "destination": "kampala"})
    assert same_location.status_code == 400
    invalid_shape = client.post("/api/route", json=["Kampala", "Entebbe"])
    assert invalid_shape.status_code == 400

    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    monkeypatch.setattr(
        "app.services.location_service.requests.get",
        lambda *args, **kwargs: type(
            "FakeResponse", (),
            {"raise_for_status": lambda self: None, "json": lambda self: []}
        )()
    )
    no_results = client.post("/api/route", json={
        "start": "No such place",
        "destination": "Entebbe Airport",
    })
    assert no_results.status_code == 422
    assert "No location found" in no_results.get_json()["error"]

def test_passenger_dashboard_shows_completed_rides_and_repeat_button(client):
    client.get("/auth/demo/passenger", follow_redirects=True)
    res = client.get("/passenger/dashboard")
    assert res.status_code == 200
    assert b"Recent Trips" in res.data
    completed_res = client.get("/passenger/rides?status=completed")
    assert b"Completed Rides" in completed_res.data
    assert b"Book again" in completed_res.data
    assert b"Fare Paid" in completed_res.data
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

    # 3. Verify rating is persisted on the dedicated rides page
    rides_res = client.get("/passenger/rides?status=completed")
    assert rides_res.status_code == 200
    assert b"5/5" in rides_res.data
    assert b"smooth driving across Kampala" in rides_res.data

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
    search_entebbe = client.get("/passenger/rides?q=Entebbe")
    assert search_entebbe.status_code == 200
    assert b"Entebbe International Airport" in search_entebbe.data
    assert b'value="Entebbe"' in search_entebbe.data

    # Test search with driver name
    search_driver = client.get("/passenger/rides?q=David")
    assert search_driver.status_code == 200
    assert b"David" in search_driver.data

    # Test search with no matching keyword
    search_none = client.get("/passenger/rides?q=NonExistentTown99")
    assert search_none.status_code == 200
    assert b"No trips match" in search_none.data

def test_passenger_workspace_pages_and_awaiting_ride_filter(client):
    client.get("/auth/demo/passenger", follow_redirects=True)
    request_res = client.post("/passenger/book-ride", data={
        "pickup_address": "Acacia Mall, Kololo",
        "destination_address": "Entebbe Airport",
        "category": "ECONOMY",
        "payment_method": "MTN_MOMO"
    }, follow_redirects=True)
    assert request_res.status_code == 200

    active_res = client.get("/passenger/rides?status=active")
    assert active_res.status_code == 200
    assert b"Active Rides" in active_res.data
    assert b"Acacia Mall, Kololo" in active_res.data
    assert client.get("/passenger/flight-requests?status=awaiting").status_code == 200
    assert client.get("/passenger/flight-requests").status_code == 200

def test_driver_workspace_pages(client):
    client.get("/auth/demo/driver", follow_redirects=True)
    assert b"Awaiting Requests" in client.get("/driver/requests").data
    assert b"Track Live Ride" in client.get("/driver/active-ride").data
    assert b"Completed Rides" in client.get("/driver/trips").data

def test_driver_weekly_earnings_summary(client, db):
    import uuid

    payment_id = f"pay_test_{uuid.uuid4().hex}"
    reference = f"rideeasy_test_{uuid.uuid4().hex}"
    db.execute(
        """INSERT INTO payment_transactions
           (id, ride_id, passenger_id, reference, amount_ugx, currency, status, created_at)
           VALUES (?, 'ride_10', 'usr_pass_01', ?, 12000, 'UGX', 'PAID', CURRENT_TIMESTAMP)""",
        (payment_id, reference)
    )
    db.execute(
        """INSERT INTO payment_ledger
           (id, payment_id, recipient_id, recipient_role, recipient_name, recipient_phone, amount_ugx)
           VALUES (?, ?, 'usr_driver_01', 'DRIVER', 'David Okello', '0772000000', 9600)""",
        (f"led_test_{uuid.uuid4().hex}", payment_id)
    )

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

def test_passenger_rewards_tracker_and_redemption(client, db):
    # 1. Login as passenger
    client.get("/auth/demo/passenger", follow_redirects=True)

    ride = db.fetchone("SELECT estimated_distance_km FROM rides WHERE id = 'ride_01'")
    original_distance = ride["estimated_distance_km"]
    db.execute("UPDATE rides SET estimated_distance_km = 500 WHERE id = 'ride_01'")

    # 2. View the dedicated rewards page
    rewards_res = client.get("/passenger/rewards")
    assert rewards_res.status_code == 200
    assert b"RideEasy Rewards" in rewards_res.data
    assert b"Available Points" in rewards_res.data
    assert b"Trip Distance" in rewards_res.data
    assert b"Current Tier" in rewards_res.data
    assert b"Redeemable Travel Benefits" in rewards_res.data

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

    # 4. Redeem the least expensive unlocked benefit
    benefit = next(item for item in rewards["benefits"] if item["can_redeem"])
    redeem_res = client.post("/passenger/rewards/redeem", json={
        "reward_id": benefit["id"]
    }, headers={"X-Requested-With": "XMLHttpRequest"})
    assert redeem_res.status_code == 200
    redeem_data = redeem_res.get_json()
    assert redeem_data["success"] is True
    assert "voucher" in redeem_data
    assert redeem_data["voucher"]["title"] == benefit["title"]
    assert redeem_data["rewards"]["available_points"] == initial_pts - benefit["points_cost"]

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

    db.execute("UPDATE rides SET estimated_distance_km = ? WHERE id = 'ride_01'", (original_distance,))
