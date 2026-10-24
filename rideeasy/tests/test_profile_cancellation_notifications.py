from app.repositories.database import get_db


def test_profile_view_and_update(client):
    """Test user can view profile and update full name, email, and phone."""
    # Log in as demo passenger
    client.get("/auth/demo/passenger", follow_redirects=True)
    
    # 1. View profile page
    res = client.get("/profile")
    assert res.status_code == 200
    assert b"User Profile" in res.data
    assert b"Personal Information" in res.data

    # 2. Server-side validation failure test (invalid email)
    res_bad = client.post("/profile", data={
        "full_name": "Test Passenger",
        "email": "not-an-email",
        "phone": "+256 772 123 456"
    }, follow_redirects=True)
    assert b"Please enter a valid email address" in res_bad.data

    # 3. Successful update
    res_good = client.post("/profile", data={
        "full_name": "Kato Brian Updated",
        "email": "passenger@rideeasy.ug",
        "phone": "+256 700 999 888",
        "preferred_payment_method": "MTN_MOMO",
        "home_address": "Plot 10 Acacia Avenue",
        "work_address": "Crested Towers"
    }, follow_redirects=True)
    assert res_good.status_code == 200
    assert b"successfully updated" in res_good.data

    # Verify update in database
    db = get_db()
    user = db.fetchone("SELECT full_name, phone FROM users WHERE email = 'passenger@rideeasy.ug'")
    assert user["full_name"] == "Kato Brian Updated"
    assert user["phone"] == "+256 700 999 888"

    # Restore default demo user profile state for test isolation
    client.post("/profile", data={
        "full_name": "Grace Namubiru",
        "email": "passenger@rideeasy.ug",
        "phone": "+256 772 123 456",
        "preferred_payment_method": "MTN_MOMO",
        "home_address": "Plot 14 Acacia Avenue, Kololo",
        "work_address": "Victoria Towers, Nakasero Road"
    }, follow_redirects=True)


def test_ride_cancellation_workflow(client):
    """Test cancellation before assignment and after driver acceptance."""
    client.get("/auth/demo/passenger", follow_redirects=True)
    db = get_db()

    # Create a fresh unassigned ride in REQUESTED status
    import uuid
    user = db.fetchone("SELECT id FROM users WHERE email = 'passenger@rideeasy.ug'")
    ride_id = f"ride_{uuid.uuid4().hex[:10]}"
    db.execute(
        """INSERT INTO rides 
        (id, passenger_id, category, pickup_address, pickup_lat, pickup_lng, 
         destination_address, destination_lat, destination_lng, estimated_distance_km, 
         estimated_fare_ugx, final_fare_ugx, payment_method, status) 
        VALUES (?, ?, 'ECONOMY', 'Kisementi', 0.334, 32.585, 'Garden City', 0.318, 32.590, 3.5, 9500, 9500, 'CASH', 'REQUESTED')""",
        (ride_id, user["id"])
    )

    # View cancellation confirmation step (should display rules)
    res_rules = client.get(f"/passenger/rides/{ride_id}/cancel")
    assert res_rules.status_code == 200
    assert b"Official RideEasy Cancellation Rules" in res_rules.data
    assert b"Cancellation before pickup" in res_rules.data
    assert b"Confirmation Step" in res_rules.data

    # Confirm cancellation
    res_cancel = client.post(f"/passenger/rides/{ride_id}/cancel", data={
        "reason": "Wait time is longer than expected",
        "custom_notes": "Had to leave urgently"
    }, follow_redirects=True)
    assert res_cancel.status_code == 200
    assert b"cancelled" in res_cancel.data

    # Verify status and reason in database
    updated_ride = db.fetchone("SELECT status, cancellation_reason, cancelled_at FROM rides WHERE id = ?", (ride_id,))
    assert updated_ride["status"] == "CANCELLED"
    assert "Wait time is longer than expected" in updated_ride["cancellation_reason"]
    assert updated_ride["cancelled_at"] is not None

    # Test protection when driver is already assigned
    driver = db.fetchone("SELECT id FROM users WHERE role = 'DRIVER'")
    ride_assigned_id = f"ride_{uuid.uuid4().hex[:10]}"
    db.execute(
        """INSERT INTO rides 
        (id, passenger_id, driver_id, category, pickup_address, pickup_lat, pickup_lng, 
         destination_address, destination_lat, destination_lng, estimated_distance_km, 
         estimated_fare_ugx, final_fare_ugx, payment_method, status) 
        VALUES (?, ?, ?, 'ECONOMY', 'Kisementi', 0.334, 32.585, 'Garden City', 0.318, 32.590, 3.5, 9500, 9500, 'CASH', 'DRIVER_ASSIGNED')""",
        (ride_assigned_id, user["id"], driver["id"])
    )

    # An assigned driver does not block cancellation before the trip starts.
    res_locked_get = client.get(f"/passenger/rides/{ride_assigned_id}/cancel")
    assert b"Your driver has accepted this ride." in res_locked_get.data

    res_assigned_cancel = client.post(f"/passenger/rides/{ride_assigned_id}/cancel", data={
        "reason": "Changed my mind"
    }, follow_redirects=True)
    assert b"Ride cancelled" in res_assigned_cancel.data
    assert db.fetchone(
        "SELECT status FROM rides WHERE id = ?", (ride_assigned_id,)
    )["status"] == "CANCELLED"
    assert db.fetchone(
        "SELECT title FROM notifications WHERE user_id = ? AND related_entity_id = ? ORDER BY rowid DESC LIMIT 1",
        (driver["id"], ride_assigned_id),
    )["title"] == "Passenger cancelled the ride"

    ride_started_id = f"ride_{uuid.uuid4().hex[:10]}"
    db.execute(
        """INSERT INTO rides
        (id, passenger_id, driver_id, category, pickup_address, pickup_lat, pickup_lng,
         destination_address, destination_lat, destination_lng, estimated_distance_km,
         estimated_fare_ugx, final_fare_ugx, payment_method, status)
        VALUES (?, ?, ?, 'ECONOMY', 'Kisementi', 0.334, 32.585, 'Garden City',
                0.318, 32.590, 3.5, 9500, 9500, 'CASH', 'TRIP_STARTED')""",
        (ride_started_id, user["id"], driver["id"])
    )
    res_started_cancel = client.post(
        f"/passenger/rides/{ride_started_id}/cancel",
        data={"reason": "Changed my mind"},
        follow_redirects=True,
    )
    assert b"can no longer be cancelled online" in res_started_cancel.data
    assert db.fetchone(
        "SELECT status FROM rides WHERE id = ?", (ride_started_id,)
    )["status"] == "TRIP_STARTED"

def test_in_app_notification_system(client):
    """Test creating, displaying, and dismissing notifications for driver assignment."""
    client.get("/auth/demo/passenger", follow_redirects=True)
    db = get_db()
    user = db.fetchone("SELECT id FROM users WHERE email = 'passenger@rideeasy.ug'")

    from app.services.notification_service import NotificationService
    notif_id = NotificationService.create_notification(
        user_id=user["id"],
        title="Driver Assigned",
        message="Mugisha Samuel (UBJ 452X Toyota Fielder) accepted your ride and is en route.",
        notif_type="DRIVER_ASSIGNED"
    )

    # Verify notification appears on dashboard
    res_dash = client.get("/passenger/dashboard")
    assert res_dash.status_code == 200
    assert b"Driver Assigned" in res_dash.data
    assert b"Mugisha Samuel" in res_dash.data
    assert b"Dismiss" in res_dash.data

    # Dismiss notification
    res_dismiss = client.post(f"/notifications/{notif_id}/dismiss", follow_redirects=True)
    assert res_dismiss.status_code == 200

    # Verify notification is marked as read in database
    notif = db.fetchone("SELECT is_read FROM notifications WHERE id = ?", (notif_id,))
    assert notif["is_read"] == 1
