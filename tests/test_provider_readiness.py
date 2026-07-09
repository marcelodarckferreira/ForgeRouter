from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_admin_provider_readiness_is_public_read_only(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.get("/admin/providers/readiness")

    assert response.status_code == 200


def test_admin_provider_readiness_reports_key_presence_without_secret(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "secret-value")

    response = client.get("/admin/providers/readiness")

    assert response.status_code == 200
    providers = response.json()["providers"]
    groq = next(item for item in providers if item["provider"] == "groq")
    assert groq["api_key_env"] == "GROQ_API_KEY"
    assert groq["api_key_configured"] is True
    assert "secret-value" not in response.text
