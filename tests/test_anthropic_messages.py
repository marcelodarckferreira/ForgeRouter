import json

from fastapi.testclient import TestClient

from app.main import app
from app.registry import ProviderModel, ProviderRegistry

client = TestClient(app)


def model(model_id: str = "groq/llama-3.3-70b-versatile") -> ProviderModel:
    return ProviderModel(
        id=model_id,
        provider="groq",
        provider_model=model_id.split("/", 1)[1],
        tier=1,
        capabilities=["text", "tool_call"],
        enabled=True,
        healthy=True,
        base_url="https://api.groq.com/openai/v1",
        api_key_env="GROQ_API_KEY",
    )


ANTHROPIC_TOOLS = [
    {
        "name": "get_weather",
        "description": "Weather lookup",
        "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
    }
]


def test_anthropic_messages_converts_tools_and_tool_results(monkeypatch):
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([model()]))
    monkeypatch.setattr("app.main.persist_route_event", lambda *args, **kwargs: None)
    captured = {}

    def fake_chat_completion(selected, payload):
        captured.update(payload)
        return 200, {
            "choices": [{"message": {"role": "assistant", "content": "25C em SP"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 4},
        }

    monkeypatch.setattr("app.main.chat_completion", fake_chat_completion)

    response = client.post(
        "/v1/messages",
        json={
            "model": "groq/llama-3.3-70b-versatile",
            "max_tokens": 64,
            "tools": ANTHROPIC_TOOLS,
            "messages": [
                {"role": "user", "content": "clima em SP?"},
                {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_1", "name": "get_weather", "input": {"city": "SP"}}]},
                {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "25C"}]},
            ],
        },
    )

    assert response.status_code == 200
    # Anthropic input_schema must reach the provider as OpenAI function parameters.
    tool = captured["tools"][0]
    assert tool["type"] == "function"
    assert tool["function"]["name"] == "get_weather"
    assert tool["function"]["parameters"]["properties"]["city"]["type"] == "string"
    # tool_use becomes assistant tool_calls; tool_result becomes a role:"tool" message.
    assistant = next(m for m in captured["messages"] if m["role"] == "assistant")
    call = assistant["tool_calls"][0]
    assert call["id"] == "toolu_1"
    assert call["function"]["name"] == "get_weather"
    assert json.loads(call["function"]["arguments"]) == {"city": "SP"}
    tool_message = next(m for m in captured["messages"] if m["role"] == "tool")
    assert tool_message["tool_call_id"] == "toolu_1"
    assert tool_message["content"] == "25C"


def test_anthropic_messages_returns_tool_use_blocks(monkeypatch):
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([model()]))
    monkeypatch.setattr("app.main.persist_route_event", lambda *args, **kwargs: None)

    def fake_chat_completion(selected, payload):
        return 200, {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {"id": "call_1", "type": "function", "function": {"name": "get_weather", "arguments": '{"city": "SP"}'}}
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 9, "completion_tokens": 3},
        }

    monkeypatch.setattr("app.main.chat_completion", fake_chat_completion)

    response = client.post(
        "/v1/messages",
        json={
            "model": "groq/llama-3.3-70b-versatile",
            "max_tokens": 64,
            "tools": ANTHROPIC_TOOLS,
            "messages": [{"role": "user", "content": "clima em SP?"}],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["stop_reason"] == "tool_use"
    block = body["content"][0]
    assert block["type"] == "tool_use"
    assert block["id"] == "call_1"
    assert block["name"] == "get_weather"
    assert block["input"] == {"city": "SP"}
    assert body["usage"] == {"input_tokens": 9, "output_tokens": 3}


def test_anthropic_messages_plain_text_roundtrip(monkeypatch):
    monkeypatch.setattr("app.main.load_registry_with_db_health", lambda: ProviderRegistry([model()]))
    monkeypatch.setattr("app.main.persist_route_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "app.main.chat_completion",
        lambda selected, payload: (
            200,
            {"choices": [{"message": {"role": "assistant", "content": "oi"}, "finish_reason": "stop"}], "usage": {}},
        ),
    )

    response = client.post(
        "/v1/messages",
        json={"model": "groq/llama-3.3-70b-versatile", "max_tokens": 16, "messages": [{"role": "user", "content": "oi"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["content"] == [{"type": "text", "text": "oi"}]
    assert body["stop_reason"] == "end_turn"
