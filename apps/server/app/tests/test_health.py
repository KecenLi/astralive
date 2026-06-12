from fastapi.testclient import TestClient

from app.main import app


def test_health_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_public_config_has_mock_providers() -> None:
    client = TestClient(app)
    response = client.get("/api/config/public")
    assert response.status_code == 200
    data = response.json()
    assert data["providers"]["vision"] == "mock"
    assert data["wake_word"]

