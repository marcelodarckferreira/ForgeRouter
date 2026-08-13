import json
import time

from app.providers import xai_grok as xai_grok_module
from app.providers.xai_grok import (
    build_responses_payload,
    fold_events_to_completion,
    is_xai_grok_base_url,
    xai_grok_headers,
    xai_grok_responses_url,
    xai_grok_token,
)
from app.providers.plans import plan_for
from app.registry import ProviderModel


def test_plan_dispatch_matches_xai_grok_base_url():
    plan = plan_for("https://cli-chat-proxy.grok.com/v1")
    assert plan is not None and plan.name == "xai-grok-oauth"
    assert plan.chat_completion is not None and plan.discover_models is not None
    assert plan_for("https://api.groq.com/openai/v1") is None
    assert is_xai_grok_base_url("https://cli-chat-proxy.grok.com/v1")


def test_xai_grok_responses_url_appends_responses_path():
    assert xai_grok_responses_url("https://cli-chat-proxy.grok.com/v1") == "https://cli-chat-proxy.grok.com/v1/responses"


def test_xai_grok_token_falls_back_to_auth_file_and_refreshes_when_expired(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"access_token": "fresh-tok", "refresh_token": "r1", "expires_at": time.time() + 3600}))
    monkeypatch.setattr(xai_grok_module, "XAI_AUTH_FILE", str(auth))
    assert xai_grok_token("stored", "") == "stored"
    assert xai_grok_token("", "") == "fresh-tok"

    def fake_refresh(_auth):
        return {"access_token": "refreshed-tok"}

    auth.write_text(json.dumps({"access_token": "stale-tok", "refresh_token": "r1", "expires_at": time.time() - 10}))
    monkeypatch.setattr(xai_grok_module, "_refresh", fake_refresh)
    assert xai_grok_token("", "") == "refreshed-tok"


def test_xai_grok_headers_include_proxy_identity_and_model_override(monkeypatch):
    monkeypatch.setattr(xai_grok_module, "xai_grok_token", lambda api_key, api_key_env: "tok-123")
    model = ProviderModel(
        id="xai-grok-oauth/grok-4.5",
        provider="xai-grok-oauth",
        provider_model="grok-4.5",
        tier=1,
        capabilities=["text"],
        enabled=True,
        healthy=True,
        base_url="https://cli-chat-proxy.grok.com/v1",
    )
    headers = xai_grok_headers(model)
    assert headers["Authorization"] == "Bearer tok-123"
    assert headers["X-XAI-Token-Auth"] == "xai-grok-cli"
    assert headers["x-grok-model-override"] == "grok-4.5"


def test_build_responses_payload_translates_chat_shape():
    payload = build_responses_payload(
        {
            "model": "grok-4.5",
            "messages": [
                {"role": "system", "content": "be terse"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": "42"},
            ],
            "tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}],
            "temperature": 0,
            "stream": False,
        }
    )
    assert payload["model"] == "grok-4.5"
    assert payload["instructions"] == "be terse"
    assert payload["stream"] is True and payload["store"] is False
    kinds = [item["type"] for item in payload["input"]]
    assert kinds == ["message", "function_call", "function_call_output"]
    assert payload["tools"][0] == {"type": "function", "name": "f", "description": "", "strict": False, "parameters": {"type": "object"}}


def test_fold_events_builds_chat_completion_with_usage():
    events = [
        {"type": "response.output_text.delta", "delta": "OK"},
        {"type": "response.completed", "response": {"id": "resp_1", "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}}},
    ]
    status, body = fold_events_to_completion(events, "xai-grok-oauth/grok-4.5")
    assert status == 200
    assert body["choices"][0]["message"]["content"] == "OK"
    assert body["usage"] == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}


def test_fold_events_translates_failures():
    status, body = fold_events_to_completion([{"type": "response.failed", "response": {"error": {"message": "quota"}}}], "m")
    assert status == 502
    assert body["error"]["message"] == "quota"
