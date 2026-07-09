from fastapi.testclient import TestClient

from app.main import app
from app.registry import load_registry

client = TestClient(app)


def test_registry_loads_configured_models():
    registry = load_registry("config/providers.yaml")
    model_ids = {model.id for model in registry.models}

    assert "local/qwen2.5:1.5b" in model_ids
    assert "mistral/mistral-small-latest" in model_ids


def test_models_endpoint_returns_openai_compatible_models():
    response = client.get("/v1/models")

    assert response.status_code == 200
    payload = response.json()
    assert payload["object"] == "list"
    assert any(item["id"] == "local/qwen2.5:1.5b" for item in payload["data"])


def test_chat_auto_returns_503_when_no_healthy_provider():
    response = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "Reply OK"}]},
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["type"] == "no_healthy_provider"
