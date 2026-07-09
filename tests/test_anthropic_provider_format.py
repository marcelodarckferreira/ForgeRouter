import json

from fastapi.testclient import TestClient

from app.main import app
from app.providers import anthropic_compatible
from app.providers.anthropic_compatible import anthropic_headers, anthropic_messages_url
from app.providers.claude_code import CLAUDE_CODE_SYSTEM_PROMPT, build_messages_request
from app.providers.openai_compatible import chat_completion
from app.registry import ProviderModel, registry_from_provider_dicts

client = TestClient(app)


def model(api_format: str = "anthropic", base_url: str = "https://gateway.example.com") -> ProviderModel:
    return ProviderModel(
        id="claude-gw/claude-sonnet-4-6",
        provider="claude-gw",
        provider_model="claude-sonnet-4-6",
        tier=2,
        capabilities=["text", "tool_call"],
        enabled=True,
        healthy=True,
        base_url=base_url,
        api_key="sk-test",
        api_format=api_format,
    )


def test_anthropic_messages_url_variants():
    assert anthropic_messages_url("https://api.example.com") == "https://api.example.com/v1/messages"
    assert anthropic_messages_url("https://api.example.com/v1") == "https://api.example.com/v1/messages"
    assert anthropic_messages_url("https://api.example.com/v1/messages") == "https://api.example.com/v1/messages"


def test_anthropic_headers_send_both_auth_schemes():
    headers = anthropic_headers(model())
    assert headers["x-api-key"] == "sk-test"
    assert headers["Authorization"] == "Bearer sk-test"
    assert headers["anthropic-version"] == "2023-06-01"


def test_generic_build_omits_claude_code_system_prefix():
    payload = {"messages": [{"role": "user", "content": "oi"}]}
    generic = build_messages_request(payload, "claude-sonnet-4-6", system_prefix=None)
    assert "system" not in generic
    claude_code = build_messages_request(payload, "claude-sonnet-4-6")
    assert claude_code["system"][0]["text"] == CLAUDE_CODE_SYSTEM_PROMPT


def test_chat_completion_dispatches_anthropic_format(monkeypatch):
    calls = {}

    def fake_anthropic(selected, payload, timeout=120.0):
        calls.update(model_id=selected.id, payload=payload)
        return 200, {"choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]}

    monkeypatch.setattr(anthropic_compatible, "anthropic_chat_completion", fake_anthropic)

    status, body = chat_completion(model(), {"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "oi"}]})

    assert status == 200
    assert calls["model_id"] == "claude-gw/claude-sonnet-4-6"
    assert body["choices"][0]["message"]["content"] == "OK"


def test_registry_defaults_api_format_to_openai():
    registry = registry_from_provider_dicts(
        [
            {
                "name": "groq",
                "tier": 1,
                "base_url": "https://api.groq.com/openai/v1",
                "enabled": True,
                "models": [{"id": "groq/llama-3.3-70b", "enabled": True, "healthy": True}],
            },
            {
                "name": "claude-gw",
                "tier": 2,
                "base_url": "https://gateway.example.com",
                "api_format": "anthropic",
                "enabled": True,
                "models": [{"id": "claude-gw/claude-sonnet-4-6", "enabled": True, "healthy": True}],
            },
        ]
    )
    by_provider = {m.provider: m for m in registry.models}
    assert by_provider["groq"].api_format == "openai"
    assert by_provider["claude-gw"].api_format == "anthropic"


VALID_PAYLOAD = {
    "name": "claude-gw",
    "tier": 2,
    "base_url": "https://gateway.example.com",
    "enabled": True,
    "models": [
        {
            "id": "claude-gw/claude-sonnet-4-6",
            "provider_model": "claude-sonnet-4-6",
            "capabilities": ["text"],
            "enabled": True,
            "health": {"status": "healthy", "http_code": 200, "latency_ms": 900, "error": None},
        }
    ],
}


def test_upsert_provider_persists_api_format(monkeypatch):
    saved = {}
    monkeypatch.setattr("app.main.upsert_provider", lambda payload: saved.update(payload))

    response = client.put("/admin/providers/claude-gw", json={**VALID_PAYLOAD, "api_format": "anthropic"})

    assert response.status_code == 200
    assert saved["api_format"] == "anthropic"

    # Default: providers are OpenAI-compatible unless marked otherwise.
    client.put("/admin/providers/claude-gw", json=VALID_PAYLOAD)
    assert saved["api_format"] == "openai"


def test_upsert_provider_rejects_invalid_api_format(monkeypatch):
    monkeypatch.setattr("app.main.upsert_provider", lambda payload: None)

    response = client.put("/admin/providers/claude-gw", json={**VALID_PAYLOAD, "api_format": "grpc"})

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_payload"


def test_generic_anthropic_request_converts_tools():
    payload = {
        "messages": [{"role": "user", "content": "clima?"}],
        "tools": [{"type": "function", "function": {"name": "get_weather", "parameters": {"type": "object", "properties": {}}}}],
        "max_tokens": 64,
    }
    request = build_messages_request(payload, "claude-sonnet-4-6", system_prefix=None)
    assert request["tools"][0]["name"] == "get_weather"
    assert request["tools"][0]["input_schema"] == {"type": "object", "properties": {}}
    assert request["max_tokens"] == 64
    assert json.dumps(request)  # payload must be JSON-serializable
