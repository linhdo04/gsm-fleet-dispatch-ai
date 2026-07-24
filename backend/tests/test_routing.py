import httpx
import respx
from fastapi.testclient import TestClient

from fleet_dispatch.config import Settings
from fleet_dispatch.main import create_app

ORIGIN = {"lat": 21.0357936, "lng": 105.8050191}
DESTINATION = {"lat": 21.0230572, "lng": 105.8459077}


def test_no_api_key_falls_back_to_haversine() -> None:
    app = create_app(Settings(environment="test", log_format="console", google_routes_api_key=None))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/routes/estimate", json={"origin": ORIGIN, "destination": DESTINATION}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["is_fallback"] is True
    assert body["provider"] == "haversine_fallback"
    assert body["distance_m"] > 0


@respx.mock
def test_successful_google_routes_call() -> None:
    respx.post("https://routes.googleapis.com/directions/v2:computeRoutes").mock(
        return_value=httpx.Response(
            200,
            json={
                "routes": [{"distanceMeters": 6012, "duration": "1192s", "staticDuration": "1100s"}]
            },
        )
    )
    app = create_app(
        Settings(environment="test", log_format="console", google_routes_api_key="fake-key")
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/routes/estimate", json={"origin": ORIGIN, "destination": DESTINATION}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["is_fallback"] is False
    assert body["provider"] == "google_routes"
    assert body["distance_m"] == 6012


@respx.mock
def test_api_error_falls_back_to_haversine() -> None:
    respx.post("https://routes.googleapis.com/directions/v2:computeRoutes").mock(
        return_value=httpx.Response(403, json={"error": {"message": "denied"}})
    )
    app = create_app(
        Settings(environment="test", log_format="console", google_routes_api_key="fake-key")
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/routes/estimate", json={"origin": ORIGIN, "destination": DESTINATION}
        )

    assert response.status_code == 200
    assert response.json()["is_fallback"] is True


def test_rejects_out_of_range_coordinates() -> None:
    app = create_app(Settings(environment="test", log_format="console"))

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/routes/estimate",
            json={"origin": {"lat": 999, "lng": 0}, "destination": DESTINATION},
        )

    assert response.status_code == 422
