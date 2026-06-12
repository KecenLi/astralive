from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


def test_health_ok() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_public_config_reflects_non_secret_settings() -> None:
    client = TestClient(app)
    response = client.get("/api/config/public")
    assert response.status_code == 200
    data = response.json()
    settings = get_settings()
    assert data["providers"]["vision"] == settings.vision_provider
    assert "api_key" not in str(data).lower()
    assert "credentials" not in str(data).lower()
    assert data["wake_word"]
