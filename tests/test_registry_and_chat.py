from fastapi.testclient import TestClient

from app.main import app
from app.registry import ProviderModel, ProviderRegistry, load_registry

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


def test_openai_models_declares_supported_parameters_by_capability():
    # Honest about what build_chat_payload actually forwards for this model —
    # "tools" only appears for a model the router would ever select for a
    # tool_call request in the first place.
    text_only = ProviderModel("p1/text", "p1", "text", 1, ["text"], True, True, "http://p1/v1", "")
    tool_capable = ProviderModel("p1/tools", "p1", "tools", 1, ["text", "tool_call"], True, True, "http://p1/v1", "")
    registry = ProviderRegistry([text_only, tool_capable])

    by_id = {entry["id"]: entry for entry in registry.openai_models()}

    assert by_id["p1/text"]["metadata"]["supported_parameters"] == ["temperature", "max_tokens", "stream"]
    assert by_id["p1/tools"]["metadata"]["supported_parameters"] == ["temperature", "max_tokens", "stream", "tools"]


def test_chat_auto_returns_503_when_no_healthy_provider():
    response = client.post(
        "/v1/chat/completions",
        json={"model": "auto", "messages": [{"role": "user", "content": "Reply OK"}]},
    )

    assert response.status_code == 503
    payload = response.json()
    assert payload["error"]["type"] == "no_healthy_provider"
