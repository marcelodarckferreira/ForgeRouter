from fastapi.testclient import TestClient

from app.main import app
from app.registry import ProviderModel, ProviderRegistry

client = TestClient(app)


def test_embeddings_success(monkeypatch):
    model = ProviderModel("p1/embed-a", "p1", "embed-a", 1, ["embedding"], True, True, "http://first/v1", "")
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([model]))

    calls = []
    def fake_embeddings(model, payload):
        calls.append((model.id, payload))
        return 200, {"object": "list", "data": [{"object": "embedding", "index": 0, "embedding": [0.1, 0.2, 0.3]}], "usage": {"prompt_tokens": 3, "total_tokens": 3}}

    monkeypatch.setattr("app.main.embeddings", fake_embeddings)
    monkeypatch.setattr("app.main.persist_route_event", lambda *args, **kwargs: None)

    response = client.post("/v1/embeddings", json={"input": "hello world"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"][0]["embedding"] == [0.1, 0.2, 0.3]
    assert body["model"] == "p1/embed-a"
    assert calls == [("p1/embed-a", {"model": "embed-a", "input": "hello world"})]


def test_embeddings_only_considers_embedding_capable_models(monkeypatch):
    text_only = ProviderModel("p1/text", "p1", "text", 1, ["text"], True, True, "http://first/v1", "")
    embed = ProviderModel("p2/embed", "p2", "embed", 2, ["embedding"], True, True, "http://second/v1", "")
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([text_only, embed]))

    calls = []
    def fake_embeddings(model, payload):
        calls.append(model.id)
        return 200, {"data": [{"embedding": [0.1]}]}

    monkeypatch.setattr("app.main.embeddings", fake_embeddings)
    monkeypatch.setattr("app.main.persist_route_event", lambda *args, **kwargs: None)

    response = client.post("/v1/embeddings", json={"input": "hi"})

    assert response.status_code == 200
    assert calls == ["p2/embed"]


def test_embeddings_falls_back_to_next_candidate(monkeypatch):
    first = ProviderModel("p1/embed-a", "p1", "embed-a", 1, ["embedding"], True, True, "http://first/v1", "")
    second = ProviderModel("p2/embed-b", "p2", "embed-b", 2, ["embedding"], True, True, "http://second/v1", "")
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([first, second]))

    calls = []
    def fake_embeddings(model, payload):
        calls.append(model.id)
        if model.id == "p1/embed-a":
            return 500, {"error": {"message": "fail"}}
        return 200, {"data": [{"embedding": [0.5]}]}

    monkeypatch.setattr("app.main.embeddings", fake_embeddings)
    monkeypatch.setattr("app.main.persist_route_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.mark_runtime_failure_unhealthy", lambda *args, **kwargs: None)

    response = client.post("/v1/embeddings", json={"input": "hi"})

    assert response.status_code == 200
    assert calls == ["p1/embed-a", "p2/embed-b"]
    assert response.headers["x-proxyrouter-model"] == "p2/embed-b"


def test_embeddings_falls_back_on_200_with_empty_data(monkeypatch):
    # An HTTP 200 with no usable vectors must be treated as a provider failure,
    # not forwarded to the caller as success — same rule as detect_silent_failure
    # for chat completions.
    first = ProviderModel("p1/embed-a", "p1", "embed-a", 1, ["embedding"], True, True, "http://first/v1", "")
    second = ProviderModel("p2/embed-b", "p2", "embed-b", 2, ["embedding"], True, True, "http://second/v1", "")
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([first, second]))

    calls = []
    def fake_embeddings(model, payload):
        calls.append(model.id)
        if model.id == "p1/embed-a":
            return 200, {"object": "list", "data": []}
        return 200, {"data": [{"embedding": [0.9]}]}

    unhealthy_calls = []
    monkeypatch.setattr("app.main.embeddings", fake_embeddings)
    monkeypatch.setattr("app.main.persist_route_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.mark_runtime_failure_unhealthy", lambda model, status_code, error_message, cooldown_seconds=None: unhealthy_calls.append((model.id, status_code, error_message)))

    response = client.post("/v1/embeddings", json={"input": "hi"})

    assert response.status_code == 200
    assert calls == ["p1/embed-a", "p2/embed-b"]
    assert unhealthy_calls == [("p1/embed-a", 200, "runtime_invalid_response")]


def test_embeddings_requested_model_falls_back_on_provider_error(monkeypatch):
    first = ProviderModel("p1/embed-a", "p1", "embed-a", 1, ["embedding"], True, True, "http://first/v1", "")
    second = ProviderModel("p2/embed-b", "p2", "embed-b", 2, ["embedding"], True, True, "http://second/v1", "")
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([first, second]))

    calls = []
    def fake_embeddings(model, payload):
        calls.append(model.id)
        if model.id == "p2/embed-b":
            return 429, {"error": {"message": "rate limited"}}
        return 200, {"data": [{"embedding": [0.4]}]}

    monkeypatch.setattr("app.main.embeddings", fake_embeddings)
    monkeypatch.setattr("app.main.persist_route_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.mark_runtime_failure_unhealthy", lambda *args, **kwargs: None)

    response = client.post("/v1/embeddings", json={"model": "p2/embed-b", "input": "hi"})

    assert response.status_code == 200
    assert calls == ["p2/embed-b", "p1/embed-a"]
    assert response.headers["x-proxyrouter-model"] == "p1/embed-a"


def test_embeddings_no_healthy_candidates(monkeypatch):
    text_only = ProviderModel("p1/text", "p1", "text", 1, ["text"], True, True, "http://first/v1", "")
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([text_only]))

    response = client.post("/v1/embeddings", json={"input": "hi"})

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "all_providers_failed"


def test_embeddings_all_candidates_fail(monkeypatch):
    model = ProviderModel("p1/embed-a", "p1", "embed-a", 1, ["embedding"], True, True, "http://first/v1", "")
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([model]))

    def fake_embeddings(model, payload):
        return 500, {"error": {"message": "down"}}

    monkeypatch.setattr("app.main.embeddings", fake_embeddings)
    monkeypatch.setattr("app.main.persist_route_event", lambda *args, **kwargs: None)
    monkeypatch.setattr("app.main.mark_runtime_failure_unhealthy", lambda *args, **kwargs: None)

    response = client.post("/v1/embeddings", json={"input": "hi"})

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "all_providers_failed"
