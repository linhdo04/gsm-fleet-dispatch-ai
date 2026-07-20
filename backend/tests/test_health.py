from fastapi.testclient import TestClient

from fleet_dispatch.config import Settings
from fleet_dispatch.main import create_app


def test_liveness_returns_request_id() -> None:
    app = create_app(Settings(environment="test", log_format="console"))

    with TestClient(app) as client:
        response = client.get("/api/v1/health/live", headers={"X-Request-ID": "test-id"})

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["X-Request-ID"] == "test-id"


def test_readiness() -> None:
    app = create_app(Settings(environment="test", log_format="console"))

    with TestClient(app) as client:
        response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_are_exposed() -> None:
    app = create_app(Settings(environment="test", log_format="console"))

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "http_requests_total" in response.text
