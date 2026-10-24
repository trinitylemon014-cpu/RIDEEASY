import pytest
import requests

from app.routes import api as api_module
from app.services.location_service import LocationIQNoResultsError, LocationService


class FakeResponse:
    def __init__(self, body):
        self.body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self.body


AUTOCOMPLETE_BODY = [
    {
        "lat": "0.3136",
        "lon": "32.5811",
        "display_name": "Acacia Mall, Kisementi, Kampala, Uganda",
        "display_place": "Acacia Mall",
        "display_address": "Kisementi, Kampala, Uganda",
    },
    {"lat": "bad", "lon": "32.0", "display_name": "Broken result"},
]


@pytest.fixture(autouse=True)
def clean_state():
    LocationService._autocomplete_cache.clear()
    api_module._autocomplete_hits.clear()
    api_module._reverse_hits.clear()
    api_module._estimate_hits.clear()
    yield
    LocationService._autocomplete_cache.clear()
    api_module._autocomplete_hits.clear()
    api_module._reverse_hits.clear()
    api_module._estimate_hits.clear()


def test_autocomplete_is_available_without_login(client, app, monkeypatch):
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    monkeypatch.setattr(
        "app.services.location_service.requests.get",
        lambda *args, **kwargs: FakeResponse(AUTOCOMPLETE_BODY),
    )
    response = client.get("/api/places/autocomplete?q=Acacia")
    assert response.status_code == 200
    assert len(response.get_json()["suggestions"]) == 1


def test_autocomplete_short_query_makes_no_provider_call(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    calls = []
    monkeypatch.setattr(
        "app.services.location_service.requests.get",
        lambda *a, **k: calls.append(1) or FakeResponse([]),
    )
    response = client.get("/api/places/autocomplete?q=Ac")
    assert response.status_code == 200
    assert response.get_json()["suggestions"] == []
    assert calls == []


def test_autocomplete_returns_clean_suggestions_and_caches(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    seen = []

    def fake_get(url, params, timeout):
        seen.append((url, params))
        return FakeResponse(AUTOCOMPLETE_BODY)

    monkeypatch.setattr("app.services.location_service.requests.get", fake_get)
    response = client.get("/api/places/autocomplete?q=Acacia")
    data = response.get_json()
    assert response.status_code == 200
    assert len(data["suggestions"]) == 1  # malformed result is dropped
    assert data["suggestions"][0]["title"] == "Acacia Mall"
    assert data["suggestions"][0]["lat"] == pytest.approx(0.3136)
    assert seen[0][1]["countrycodes"] == "ug"
    assert b"test-locationiq-key" not in response.data

    client.get("/api/places/autocomplete?q=acacia")
    assert len(seen) == 1  # second search served from cache


def test_autocomplete_reports_missing_configuration(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "")
    response = client.get("/api/places/autocomplete?q=Acacia")
    assert response.status_code == 503
    assert response.get_json()["suggestions"] == []


def test_geocoding_does_not_fall_back_outside_uganda(app, monkeypatch):
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    requests_seen = []

    def no_results(url, params, timeout):
        requests_seen.append(params.copy())
        return FakeResponse([])

    monkeypatch.setattr("app.services.location_service.requests.get", no_results)
    with app.app_context(), pytest.raises(LocationIQNoResultsError):
        LocationService.geocode("An unknown place")

    assert len(requests_seen) == 1
    assert requests_seen[0]["countrycodes"] == "ug"


def test_autocomplete_is_throttled_per_user(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    monkeypatch.setattr(api_module, "AUTOCOMPLETE_MAX_PER_MINUTE", 2)
    monkeypatch.setattr(
        "app.services.location_service.requests.get",
        lambda url, params, timeout: FakeResponse(AUTOCOMPLETE_BODY),
    )
    codes = [client.get(f"/api/places/autocomplete?q=Acacia{i}").status_code for i in range(3)]
    assert codes == [200, 200, 429]


def test_route_uses_picked_coordinates_without_geocoding(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    urls = []

    def fake_get(url, params, timeout):
        urls.append(url)
        return FakeResponse({
            "routes": [{
                "distance": 42100,
                "duration": 5400,
                "geometry": {"type": "LineString", "coordinates": [[32.58, 0.31], [32.44, 0.04]]},
            }]
        })

    monkeypatch.setattr("app.services.location_service.requests.get", fake_get)
    response = client.post("/api/route", json={
        "start": "Acacia Mall, Kisementi, Kampala, Uganda",
        "destination": "Entebbe International Airport, Uganda",
        "start_point": {"lat": 0.3136, "lng": 32.5811, "label": "Acacia Mall, Kisementi, Kampala, Uganda"},
        "destination_point": {"lat": 0.0424, "lng": 32.4435, "label": "Entebbe International Airport, Uganda"},
    })
    assert response.status_code == 200
    assert len(urls) == 1 and "/directions/" in urls[0]
    assert response.get_json()["route"]["start"]["label"].startswith("Acacia Mall")


def test_route_ignores_invalid_picked_coordinates(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    urls = []

    def fake_get(url, params, timeout):
        urls.append(url)
        if url.endswith("/search"):
            return FakeResponse([{"lat": "0.3", "lon": "32.5", "display_name": "Somewhere"}])
        return FakeResponse({
            "routes": [{
                "distance": 1000,
                "duration": 60,
                "geometry": {"type": "LineString", "coordinates": [[32.5, 0.3], [32.51, 0.31]]},
            }]
        })

    monkeypatch.setattr("app.services.location_service.requests.get", fake_get)
    response = client.post("/api/route", json={
        "start": "Place A",
        "destination": "Place B",
        "start_point": {"lat": 999, "lng": "x"},
        "destination_point": "nope",
    })
    assert response.status_code == 200
    assert sum(u.endswith("/search") for u in urls) == 2  # fell back to geocoding


def _provider_error(status, body):
    response = requests.Response()
    response.status_code = status
    response._content = body
    return response


def test_reverse_requires_login(client):
    response = client.get("/api/places/reverse?lat=0.31&lng=32.58")
    assert response.status_code in (301, 302, 401, 403)


@pytest.mark.parametrize("query", ["", "lat=abc&lng=32", "lat=95&lng=32", "lat=0.3&lng=181", "lat=nan&lng=1"])
def test_reverse_rejects_invalid_coordinates(client, app, monkeypatch, query):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    response = client.get(f"/api/places/reverse?{query}")
    assert response.status_code == 400


def test_reverse_names_the_current_place(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    seen = []

    def fake_get(url, params, timeout):
        seen.append((url, params))
        return FakeResponse({"display_name": "Acacia Avenue, Kololo, Kampala, Uganda"})

    monkeypatch.setattr("app.services.location_service.requests.get", fake_get)
    response = client.get("/api/places/reverse?lat=0.3136&lng=32.5811")
    data = response.get_json()
    assert response.status_code == 200
    assert data["place"]["label"].startswith("Acacia Avenue")
    assert data["place"]["lat"] == pytest.approx(0.3136)
    assert seen[0][0].endswith("/reverse")
    assert b"test-locationiq-key" not in response.data


def test_reverse_falls_back_to_coordinates_when_nothing_is_mapped(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    monkeypatch.setattr(
        "app.services.location_service.requests.get",
        lambda url, params, timeout: _provider_error(404, b'{"error":"Unable to geocode"}'),
    )
    response = client.get("/api/places/reverse?lat=0.5&lng=32.5")
    assert response.status_code == 200
    assert response.get_json()["place"]["label"] == "Current location (0.50000, 32.50000)"


def test_reverse_reports_provider_failure_and_missing_config(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "")
    assert client.get("/api/places/reverse?lat=0.5&lng=32.5").status_code == 503

    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    monkeypatch.setattr(
        "app.services.location_service.requests.get",
        lambda url, params, timeout: _provider_error(401, b'{"error":"Invalid key"}'),
    )
    assert client.get("/api/places/reverse?lat=0.5&lng=32.5").status_code == 502


def test_reverse_is_throttled_per_user(client, app, monkeypatch):
    client.get("/auth/demo/passenger", follow_redirects=True)
    monkeypatch.setitem(app.config, "LOCATIONIQ_API_KEY", "test-locationiq-key")
    monkeypatch.setattr(api_module, "REVERSE_MAX_PER_MINUTE", 1)
    monkeypatch.setattr(
        "app.services.location_service.requests.get",
        lambda url, params, timeout: FakeResponse({"display_name": "Somewhere, Uganda"}),
    )
    codes = [client.get("/api/places/reverse?lat=0.5&lng=32.5").status_code for _ in range(2)]
    assert codes == [200, 429]


def test_map_page_has_current_location_button(client):
    client.get("/auth/demo/passenger", follow_redirects=True)
    page = client.get("/map")
    assert b"use-my-location" in page.data
