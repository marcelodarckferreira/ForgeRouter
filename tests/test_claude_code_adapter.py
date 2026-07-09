import json

from app.providers import claude_code as claude_code_module
from app.providers.claude_code import (
    CLAUDE_CODE_SYSTEM_PROMPT,
    build_messages_request,
    claude_code_messages_url,
    claude_code_token,
    fold_message_to_completion,
    is_claude_code_base_url,
    iter_sse_events,
    stream_events_as_chunks,
)
from app.providers.plans import plan_for


def test_plan_dispatch_matches_claude_code_base_url():
    plan = plan_for("https://api.anthropic.com/v1")
    assert plan is not None and plan.name == "claude-code"
    assert plan.chat_completion is not None and plan.discover_models is not None
    assert plan_for("https://api.groq.com/openai/v1") is None
    assert is_claude_code_base_url("https://api.anthropic.com/v1")


def test_plan_dispatch_matches_env_configured_anthropic_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:2100")
    plan = plan_for("https://api.anthropic.com/v1")
    assert plan is not None and plan.name == "claude-code"


def test_claude_code_messages_url_uses_anthropic_base_url(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:2100")
    assert claude_code_messages_url("https://api.anthropic.com/v1") == "http://localhost:2100/v1/messages"

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://localhost:2100/v1")
    assert claude_code_messages_url("https://api.anthropic.com/v1") == "http://localhost:2100/v1/messages"


def test_claude_code_token_falls_back_to_cli_auth_file(tmp_path, monkeypatch):
    auth = tmp_path / ".credentials.json"
    auth.write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-from-cli"}}))
    monkeypatch.setattr(claude_code_module, "CLAUDE_CODE_AUTH_FILE", str(auth))
    assert claude_code_token("stored", "") == "stored"
    assert claude_code_token("", "") == "tok-from-cli"


def test_build_messages_request_translates_chat_shape():
    request = build_messages_request(
        {
            "messages": [
                {"role": "system", "content": "be terse"},
                {"role": "user", "content": "hi"},
                {"role": "assistant", "tool_calls": [{"id": "call_1", "function": {"name": "f", "arguments": "{\"x\": 1}"}}]},
                {"role": "tool", "tool_call_id": "call_1", "content": "42"},
            ],
            "tools": [{"type": "function", "function": {"name": "f", "description": "do f", "parameters": {"type": "object"}}}],
            "temperature": 0,
            "max_tokens": 128,
            "stream": False,
        },
        "claude-sonnet-4-5-20250929",
    )
    assert request["model"] == "claude-sonnet-4-5-20250929"
    assert request["max_tokens"] == 128
    assert request["temperature"] == 0
    assert request["system"] == [
        {"type": "text", "text": CLAUDE_CODE_SYSTEM_PROMPT},
        {"type": "text", "text": "be terse"},
    ]
    assert request["messages"] == [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "call_1", "name": "f", "input": {"x": 1}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "42"}]},
    ]
    assert request["tools"] == [{"name": "f", "description": "do f", "input_schema": {"type": "object"}}]
    assert "stream" not in request


def test_fold_message_builds_chat_completion_with_usage():
    body = {
        "id": "msg_123",
        "type": "message",
        "role": "assistant",
        "content": [{"type": "text", "text": "PONG"}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 28, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0, "output_tokens": 6},
    }
    status, completion = fold_message_to_completion(body, "claude-code/claude-sonnet-4-5-20250929")
    assert status == 200
    assert completion["choices"][0]["message"]["content"] == "PONG"
    assert completion["choices"][0]["finish_reason"] == "stop"
    assert completion["usage"] == {"prompt_tokens": 28, "completion_tokens": 6, "total_tokens": 34}


def test_fold_message_translates_tool_calls():
    body = {
        "id": "msg_456",
        "content": [{"type": "tool_use", "id": "toolu_1", "name": "f", "input": {"x": 1}}],
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }
    status, completion = fold_message_to_completion(body, "m")
    assert status == 200
    assert completion["choices"][0]["message"]["content"] is None
    call = completion["choices"][0]["message"]["tool_calls"][0]
    assert call["function"]["name"] == "f" and json.loads(call["function"]["arguments"]) == {"x": 1}
    assert completion["choices"][0]["finish_reason"] == "tool_calls"


def test_iter_sse_events_parses_data_lines():
    lines = ['data: {"type": "message_start"}', "", "not-data", 'data: {"type": "message_stop"}']
    events = list(iter_sse_events(lines))
    assert events == [{"type": "message_start"}, {"type": "message_stop"}]


def test_stream_events_as_chunks_emits_content_and_usage():
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 10, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 1}},
        {"type": "message_stop"},
    ]
    chunks = [json.loads(line[len(b"data: "):]) for line in stream_events_as_chunks(events, "m") if line.startswith(b"data: {")]
    assert chunks[0]["choices"][0]["delta"] == {"role": "assistant", "content": "Hi"}
    assert chunks[-1]["choices"][0]["finish_reason"] == "stop"
    assert chunks[-1]["usage"] == {"prompt_tokens": 10, "completion_tokens": 1, "total_tokens": 11}


def test_stream_events_as_chunks_emits_tool_calls():
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 5, "output_tokens": 0}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "toolu_1", "name": "f", "input": {}}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": '{"x": 1}'}},
        {"type": "content_block_stop", "index": 0},
        {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}},
    ]
    chunks = [json.loads(line[len(b"data: "):]) for line in stream_events_as_chunks(events, "m") if line.startswith(b"data: {")]
    first_delta = chunks[0]["choices"][0]["delta"]
    assert first_delta["role"] == "assistant"
    assert first_delta["tool_calls"][0] == {"index": 0, "id": "toolu_1", "type": "function", "function": {"name": "f", "arguments": ""}}
    assert chunks[1]["choices"][0]["delta"]["tool_calls"][0] == {"index": 0, "function": {"arguments": '{"x": 1}'}}
    assert chunks[-1]["choices"][0]["finish_reason"] == "tool_calls"
    assert chunks[-1]["usage"] == {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9}
