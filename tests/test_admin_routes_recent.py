from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_admin_routes_recent_returns_routes_list(monkeypatch):
    response = client.get("/admin/routes/recent")

    assert response.status_code == 200
    payload = response.json()
    assert "routes" in payload
    assert isinstance(payload["routes"], list)


def test_admin_routes_recent_is_public_read_only(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.get("/admin/routes/recent")

    assert response.status_code == 200
    assert "routes" in response.json()


def test_admin_routes_recent_accepts_bearer_token_when_configured(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.get("/admin/routes/recent", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert "routes" in response.json()
