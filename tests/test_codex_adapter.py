import base64
import json

from app.providers import codex as codex_module
from app.providers.codex import (
    account_id_from_token,
    build_responses_payload,
    codex_responses_url,
    codex_token,
    fold_events_to_completion,
    is_codex_base_url,
)
from app.providers.plans import plan_for


def fake_jwt(claims: dict) -> str:
    def b64(part: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(part).encode()).decode().rstrip("=")

    return f"{b64({'alg': 'none'})}.{b64(claims)}.sig"


def test_plan_dispatch_matches_codex_base_url():
    plan = plan_for("https://chatgpt.com/backend-api/codex")
    assert plan is not None and plan.name == "openai-codex"
    assert plan.chat_completion is not None and plan.discover_models is not None
    assert plan_for("https://api.groq.com/openai/v1") is None
    assert is_codex_base_url("https://chatgpt.com/backend-api/codex")


def test_plan_dispatch_ignores_client_openai_base_url(monkeypatch):
    monkeypatch.setenv("OpenAI_BASE_URL", "http://localhost:2100")
    plan = plan_for("https://chatgpt.com/backend-api/codex")
    assert plan is not None and plan.name == "openai-codex"


def test_codex_responses_url_ignores_client_openai_base_url(monkeypatch):
    monkeypatch.setenv("OpenAI_BASE_URL", "http://localhost:2100")
    assert codex_responses_url("https://chatgpt.com/backend-api/codex") == "https://chatgpt.com/backend-api/codex/responses"

    monkeypatch.delenv("OpenAI_BASE_URL")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:2100/v1")
    assert codex_responses_url("http://codex-proxy.internal/v1") == "http://codex-proxy.internal/v1/responses"


def test_account_id_from_token_reads_jwt_claim():
    token = fake_jwt({"https://api.openai.com/auth": {"chatgpt_account_id": "acc-123"}})
    assert account_id_from_token(token) == "acc-123"
    assert account_id_from_token("not-a-jwt") == ""


def test_codex_token_falls_back_to_cli_auth_file(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {"access_token": "tok-from-cli", "account_id": "acc-9"}}))
    monkeypatch.setattr(codex_module, "CODEX_AUTH_FILE", str(auth))
    assert codex_token("stored", "") == "stored"
    assert codex_token("", "") == "tok-from-cli"


def test_build_responses_payload_translates_chat_shape():
    payload = build_responses_payload(
        {
            "model": "gpt-5.1-codex",
            "messages": [
                {"role": "system", "content": "be terse"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "c1", "content": "42"},
            ],
            "tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}],
            "temperature": 0,
            "max_tokens": 128,
            "stream": False,
        }
    )
    assert payload["model"] == "gpt-5.1-codex"
    assert payload["instructions"] == "be terse"
    assert payload["stream"] is True and payload["store"] is False
    assert "temperature" not in payload and "max_tokens" not in payload
    kinds = [item["type"] for item in payload["input"]]
    assert kinds == ["message", "function_call", "function_call_output"]
    assert payload["tools"][0] == {"type": "function", "name": "f", "description": "", "strict": False, "parameters": {"type": "object"}}


def test_fold_events_builds_chat_completion_with_usage():
    events = [
        {"type": "response.output_text.delta", "delta": "OK"},
        {"type": "response.completed", "response": {"id": "resp_1", "usage": {"input_tokens": 7, "output_tokens": 3, "total_tokens": 10}}},
    ]
    status, body = fold_events_to_completion(events, "codex/gpt-5.1-codex")
    assert status == 200
    assert body["choices"][0]["message"]["content"] == "OK"
    assert body["choices"][0]["finish_reason"] == "stop"
    assert body["usage"] == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}


def test_fold_events_translates_tool_calls_and_failures():
    events = [
        {"type": "response.output_item.done", "item": {"type": "function_call", "call_id": "c1", "name": "f", "arguments": "{\"x\":1}"}},
        {"type": "response.completed", "response": {"id": "resp_2", "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}},
    ]
    status, body = fold_events_to_completion(events, "codex/gpt-5.1-codex")
    assert status == 200
    call = body["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "f" and call["id"] == "c1"
    assert body["choices"][0]["finish_reason"] == "tool_calls"

    status, body = fold_events_to_completion([{"type": "response.failed", "response": {"error": {"message": "quota"}}}], "m")
    assert status == 502
    assert body["error"]["message"] == "quota"
