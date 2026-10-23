def test_support_widget_is_available_to_visitors_and_signed_in_customers(client):
    visitor_response = client.get("/")
    assert visitor_response.status_code == 200
    assert b'id="ai-support-widget"' in visitor_response.data
    assert b'id="ai-support-toggle"' in visitor_response.data
    assert b"Hello. How can I help" in visitor_response.data

    client.get("/auth/demo/passenger")
    passenger_response = client.get("/passenger/dashboard")
    assert passenger_response.status_code == 200
    assert b'id="ai-support-widget"' in passenger_response.data
    assert b"Hello <strong>" in passenger_response.data
    assert b"How can I help with your RideEasy journey today?" in passenger_response.data


def test_support_widget_styles_are_served(client):
    response = client.get("/static/css/components.css")
    assert response.status_code == 200
    assert b".ai-support-widget" in response.data
    assert b"position: fixed" in response.data
