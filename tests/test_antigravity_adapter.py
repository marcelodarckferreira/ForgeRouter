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
