def test_homepage_loads(client):
    response = client.get("/")
    assert response.status_code == 200
    assert b"MOVE. TRAVEL. ARRIVE." in response.data
    assert b"RideEasy" in response.data

def test_login_page_renders(client):
    response = client.get("/auth/login")
    assert response.status_code == 200
    assert b"Sign In to RideEasy" in response.data

def test_demo_login_passenger(client):
    response = client.get("/auth/demo/passenger", follow_redirects=True)
    assert response.status_code == 200
    assert b"Welcome, Grace Namubiru" in response.data

def test_demo_login_driver(client):
    response = client.get("/auth/demo/driver", follow_redirects=True)
    assert response.status_code == 200
    assert b"David Okello" in response.data

def test_demo_login_school(client):
    response = client.get("/auth/demo/school", follow_redirects=True)
    assert response.status_code == 200
    assert b"Greenhill Academy" in response.data

def test_demo_login_travel_partner(client):
    response = client.get("/auth/demo/travel", follow_redirects=True)
    assert response.status_code == 200
    assert b"Nile Equatorial Travel" in response.data

def test_demo_login_admin(client):
    response = client.get("/auth/demo/admin", follow_redirects=True)
    assert response.status_code == 200
    assert b"Operations Desk: katongole kylee" in response.data

def test_demo_login_is_not_available_outside_testing(app):
    app.testing = False
    response = app.test_client().get("/auth/demo/passenger")
    assert response.status_code == 404
    app.testing = True

def test_logout(client):
    client.get("/auth/demo/passenger", follow_redirects=True)
    response = client.get("/auth/logout", follow_redirects=True)
    assert response.status_code == 200
    assert b"You have been signed out safely." in response.data
