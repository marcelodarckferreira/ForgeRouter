from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_admin_health_is_public_read_only(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.get("/admin/providers/health")

    assert response.status_code == 200
    assert "providers" in response.json()


def test_admin_rescan_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.post("/admin/providers/rescan")

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "unauthorized"


def test_admin_health_accepts_bearer_token_when_configured(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.get("/admin/providers/health", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert "providers" in response.json()
