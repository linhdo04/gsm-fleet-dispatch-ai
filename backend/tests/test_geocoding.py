import httpx
import respx
from fastapi.testclient import TestClient

from fleet_dispatch.config import Settings
from fleet_dispatch.main import create_app


def test_no_api_key_returns_503() -> None:
    app = create_app(
        Settings(environment="test", log_format="console", google_geocoding_api_key=None)
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/geocoding/lookup", json={"address": "17 ngo 182 Luong The Vinh"}
        )

    assert response.status_code == 503


@respx.mock
def test_successful_geocode() -> None:
    respx.get("https://maps.googleapis.com/maps/api/geocode/json").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "17 Ngo 182 P. Luong The Vinh, Thanh Xuan, Ha Noi",
                        "geometry": {"location": {"lat": 21.0, "lng": 105.8}},
                    }
                ],
            },
        )
    )
    app = create_app(
        Settings(environment="test", log_format="console", google_geocoding_api_key="fake-key")
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/geocoding/lookup", json={"address": "17 ngo 182 Luong The Vinh"}
        )

    assert response.status_code == 200
    body = response.json()
    assert body["lat"] == 21.0
    assert body["lng"] == 105.8


@respx.mock
def test_zero_results_returns_503() -> None:
    respx.get("https://maps.googleapis.com/maps/api/geocode/json").mock(
        return_value=httpx.Response(200, json={"status": "ZERO_RESULTS", "results": []})
    )
    app = create_app(
        Settings(environment="test", log_format="console", google_geocoding_api_key="fake-key")
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/geocoding/lookup", json={"address": "khong ton tai xyz123"})

    assert response.status_code == 503


def test_rejects_empty_address() -> None:
    app = create_app(Settings(environment="test", log_format="console"))

    with TestClient(app) as client:
        response = client.post("/api/v1/geocoding/lookup", json={"address": ""})

    assert response.status_code == 422
