import json

from app.providers import antigravity as antigravity_module
from app.providers.antigravity import (
    antigravity_token,
    build_generate_content_request,
    fold_response_to_completion,
    is_antigravity_base_url,
    iter_sse_events,
    stream_events_as_chunks,
)
from app.providers.plans import plan_for


def test_plan_dispatch_matches_antigravity_base_url():
    plan = plan_for("https://cloudcode-pa.googleapis.com/v1internal")
    assert plan is not None and plan.name == "google-antigravity"
    assert plan.chat_completion is not None and plan.discover_models is not None
    assert plan_for("https://api.groq.com/openai/v1") is None
    assert is_antigravity_base_url("https://cloudcode-pa.googleapis.com/v1internal")


def test_antigravity_token_falls_back_to_cli_auth_file(tmp_path, monkeypatch):
    auth = tmp_path / "antigravity-oauth-token"
    auth.write_text(json.dumps({"token": {"access_token": "tok-from-cli"}, "auth_method": "consumer"}))
    monkeypatch.setattr(antigravity_module, "ANTIGRAVITY_AUTH_FILE", str(auth))
    assert antigravity_token("stored", "") == "stored"
    assert antigravity_token("", "") == "tok-from-cli"


def test_build_generate_content_request_translates_chat_shape():
    payload = build_generate_content_request(
        {
            "messages": [
                {"role": "system", "content": "be terse"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": [{"id": "c1", "function": {"name": "f", "arguments": "{\"x\": 1}"}}]},
                {"role": "tool", "name": "f", "content": "42"},
            ],
            "tools": [{"type": "function", "function": {"name": "f", "parameters": {"type": "object"}}}],
            "temperature": 0,
            "max_tokens": 128,
            "stream": False,
        },
        "proj-123",
        "gemini-2.5-pro",
    )
    assert payload["model"] == "gemini-2.5-pro"
    assert payload["project"] == "proj-123"
    request = payload["request"]
    assert request["systemInstruction"] == {"parts": [{"text": "be terse"}]}
    assert request["generationConfig"] == {"temperature": 0, "maxOutputTokens": 128}
    roles = [content["role"] for content in request["contents"]]
    assert roles == ["user", "model", "function"]
    assert request["contents"][1]["parts"][0]["functionCall"] == {"name": "f", "args": {"x": 1}}
    assert request["contents"][2]["parts"][0]["functionResponse"] == {"name": "f", "response": {"result": "42"}}
    assert request["tools"] == [{"functionDeclarations": [{"name": "f", "description": "", "parameters": {"type": "object"}}]}]


def test_fold_response_builds_chat_completion_with_usage():
    body = {
        "response": {
            "candidates": [{"content": {"role": "model", "parts": [{"text": "OK"}]}, "finishReason": "STOP"}],
            "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3, "totalTokenCount": 10},
        }
    }
    status, completion = fold_response_to_completion(body, "antigravity/gemini-2.5-pro")
    assert status == 200
    assert completion["choices"][0]["message"]["content"] == "OK"
    assert completion["choices"][0]["finish_reason"] == "stop"
    assert completion["usage"] == {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10}


def test_fold_response_translates_tool_calls_and_failures():
    body = {
        "response": {
            "candidates": [
                {"content": {"role": "model", "parts": [{"functionCall": {"name": "f", "args": {"x": 1}}}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
        }
    }
    status, completion = fold_response_to_completion(body, "m")
    assert status == 200
    call = completion["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "f" and json.loads(call["function"]["arguments"]) == {"x": 1}
    assert completion["choices"][0]["finish_reason"] == "tool_calls"

    status, completion = fold_response_to_completion({"error": {"message": "quota"}}, "m")
    assert status == 502
    assert completion["error"]["message"] == "quota"


def test_iter_sse_events_parses_data_lines():
    lines = ['data: {"response": {"candidates": []}}', "", "not-data", 'data: {"response": {"a": 1}}']
    events = list(iter_sse_events(lines))
    assert events == [{"response": {"candidates": []}}, {"response": {"a": 1}}]


def test_stream_events_as_chunks_emits_content_and_usage():
    events = [
        {"response": {"candidates": [{"content": {"role": "model", "parts": [{"text": "Hi"}]}}]}},
        {
            "response": {
                "candidates": [{"content": {"role": "model", "parts": [{"text": ""}]}, "finishReason": "STOP"}],
                "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 1, "totalTokenCount": 3},
            }
        },
    ]
    chunks = [json.loads(line[len(b"data: "):]) for line in stream_events_as_chunks(events, "m") if line.startswith(b"data: {")]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": "Hi"}
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1]["usage"] == {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}


def test_format_messages_for_cli():
    from app.providers.antigravity import _format_messages_for_cli

    messages = [
        {"role": "system", "content": "System directive"},
        {"role": "user", "content": [{"type": "text", "text": "Hello user"}]},
        {"role": "assistant", "content": "Hello bot"},
    ]
    prompt = _format_messages_for_cli(messages)
    assert "Instructions:\nSystem directive" in prompt
    assert "User:\nHello user" in prompt
    assert "Assistant:\nHello bot" in prompt


def test_antigravity_chat_completion_with_agy_cli(monkeypatch):
    import subprocess
    from app.registry import ProviderModel
    from app.providers.antigravity import antigravity_chat_completion

    monkeypatch.setattr(antigravity_module, "_find_agy_bin", lambda: "/mock/agy")

    fake_output = json.dumps({
        "status": "SUCCESS",
        "response": "Hello from mock agy",
        "usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
    })

    class FakeCompletedProcess:
        returncode = 0
        stdout = fake_output
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: FakeCompletedProcess())

    model = ProviderModel(
        id="google-antigravity/gemini-3.7-flash-low",
        provider="google-antigravity",
        provider_model="gemini-3.7-flash-low",
        base_url="https://cloudcode-pa.googleapis.com/v1internal",
        capabilities=["text", "code"],
        enabled=True,
        healthy=True,
        tier=1,
    )
    status, res = antigravity_chat_completion(model, {"messages": [{"role": "user", "content": "hi"}]})
    assert status == 200
    assert res["choices"][0]["message"]["content"] == "Hello from mock agy"
    assert res["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

