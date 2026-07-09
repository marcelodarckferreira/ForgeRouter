from app.providers.openai_compatible import build_chat_payload
from app.registry import ProviderModel


def test_build_chat_payload_uses_provider_model():
    model = ProviderModel(
        id="local/qwen2.5:1.5b", provider="local", provider_model="qwen2.5:1.5b",
        tier=4, capabilities=["text"], enabled=True, healthy=True, base_url="http://127.0.0.1:11434/v1", api_key_env=""
    )

    payload = build_chat_payload(model, [{"role": "user", "content": "OK"}], temperature=0, max_tokens=8)

    assert payload["model"] == "qwen2.5:1.5b"
    assert payload["messages"][0]["content"] == "OK"
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == 8
