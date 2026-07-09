from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_admin_rescan_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.post("/admin/providers/rescan")

    assert response.status_code == 401
    assert response.json()["error"]["type"] == "unauthorized"


def test_admin_rescan_returns_scan_payload(monkeypatch):

    class FakeResult:
        model_id = "local/qwen2.5:1.5b"
        status = "healthy"
        http_code = 200
        latency_ms = 10
        error_message = None

    monkeypatch.setattr("app.main.scan_registry", lambda: [FakeResult()])
    monkeypatch.setattr("app.main.persist_health_results", lambda results: len(results))

    response = client.post("/admin/providers/rescan")

    assert response.status_code == 200
    payload = response.json()
    assert payload["summary"]["healthy"] == 1
    assert payload["results"][0]["model_id"] == "local/qwen2.5:1.5b"


def test_admin_rescan_syncs_selection_and_agents(monkeypatch):
    """Refresh mirrors the scan verdict into the model on/off selection and
    re-syncs every agent's associations."""

    class FakeResult:
        model_id = "groq/llama-3.1-8b-instant"
        status = "unhealthy"
        http_code = 429
        latency_ms = 10
        error_message = "rate_limited"

    results = [FakeResult()]
    selection_calls: list[list] = []
    sync_calls: list[bool] = []
    monkeypatch.setattr("app.main.scan_registry", lambda: results)
    monkeypatch.setattr("app.main.persist_health_results", lambda res: len(res))
    monkeypatch.setattr("app.main.set_models_enabled_from_health", lambda res: selection_calls.append(list(res)))
    monkeypatch.setattr("app.main.sync_agent_model_associations", lambda: sync_calls.append(True) or {})

    response = client.post("/admin/providers/rescan")

    assert response.status_code == 200
    assert selection_calls == [results]
    assert sync_calls == [True]
