"""Claude Code (Claude Pro/Max subscription) protocol adapter.

The Claude Code backend (api.anthropic.com) is not OpenAI-compatible: it speaks
Anthropic's Messages API (/v1/messages), and Claude Code's OAuth access token
(~/.claude/.credentials.json -> claudeAiOauth.accessToken) is only accepted
with `anthropic-beta: oauth-2025-04-20` and a request whose `system` prompt
begins with the exact Claude Code identification string — Anthropic's API
returns a generic rate_limit_error otherwise. This module translates
chat-completions requests into Messages API payloads and folds (or re-streams)
the response back as chat completions. As with Codex/Antigravity, ForgeRouter
does not refresh the OAuth token itself — it relies on the `claude` CLI being
run periodically on the host to keep the credentials file fresh.

Note: this OAuth token is the same credential used to run Claude Code itself,
so requests routed through this provider share the account's Pro/Max usage
with any interactive Claude Code sessions on this machine.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Iterable, Iterator

import httpx

from app.registry import ProviderModel

CLAUDE_CODE_BASE_MARKER = "api.anthropic.com"
# Claude Code requires every request's system prompt to start with this exact
# text — Anthropic's API rejects (with a generic rate_limit_error) OAuth
# requests that omit it.
CLAUDE_CODE_SYSTEM_PROMPT = "You are Claude Code, Anthropic's official CLI for Claude."

DEFAULT_MAX_TOKENS = 8192

# Static fallback model catalog — the health scan decides which ones actually
# work for the account's plan.
CLAUDE_CODE_MODELS: list[dict[str, Any]] = [
    {"id": "claude-opus-4-8", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "claude-sonnet-4-6", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "claude-sonnet-4-5-20250929", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "claude-haiku-4-5-20251001", "capabilities": ["text", "code", "tool_call", "vision"]},
]


def is_claude_code_base_url(base_url: str | None) -> bool:
    value = (base_url or "").rstrip("/")
    return CLAUDE_CODE_BASE_MARKER in value


def claude_code_messages_url(base_url: str) -> str:
    # ANTHROPIC_BASE_URL points clients at ForgeRouter. Using it as this
    # provider's upstream would make ForgeRouter recursively call itself.
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base + "/messages"
    return base + "/v1/messages"


CLAUDE_CODE_AUTH_FILE = os.environ.get("CLAUDE_CODE_AUTH_FILE", os.path.expanduser("~/.claude/.credentials.json"))

STOP_REASON_MAP = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "pause_turn": "stop",
    "refusal": "content_filter",
}


def _auth_file_token() -> str:
    try:
        with open(CLAUDE_CODE_AUTH_FILE, encoding="utf-8") as fh:
            return str((json.load(fh).get("claudeAiOauth") or {}).get("accessToken") or "")
    except Exception:
        return ""


def claude_code_discover_models() -> list[dict[str, Any]]:
    return [dict(model) for model in CLAUDE_CODE_MODELS]


def claude_code_token(api_key: str = "", api_key_env: str = "") -> str:
    """Claude Code credential resolution: stored key -> env var -> the Claude
    Code CLI login (~/.claude/.credentials.json). With `claude` logged in on
    this machine nothing needs to be stored, and the token stays fresh as the
    CLI refreshes it."""
    if api_key:
        return api_key
    if api_key_env and os.environ.get(api_key_env):
        return os.environ[api_key_env]
    return _auth_file_token()


def claude_code_headers(token: str, extra_headers: dict[str, str] | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "oauth-2025-04-20",
    }
    headers.update(extra_headers or {})
    return headers


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return "" if content is None else str(content)


def _image_block(url: str) -> dict[str, Any] | None:
    if url.startswith("data:"):
        try:
            header, data = url.split(",", 1)
            media_type = header[len("data:"):].split(";")[0] or "image/png"
            return {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": data}}
        except Exception:
            return None
    if url.startswith("http://") or url.startswith("https://"):
        return {"type": "image", "source": {"type": "url", "url": url}}
    return None


def _content_blocks(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    if content is None:
        return []
    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            text = part.get("text", "")
            if text:
                blocks.append({"type": "text", "text": text})
        elif part.get("type") == "image_url":
            block = _image_block((part.get("image_url") or {}).get("url", ""))
            if block:
                blocks.append(block)
    return blocks


def build_messages_request(chat_payload: dict[str, Any], model_id: str, system_prefix: str | None = CLAUDE_CODE_SYSTEM_PROMPT) -> dict[str, Any]:
    """chat-completions request -> Anthropic Messages API request.

    system_prefix is the OAuth particularity: Claude Code requests must open with
    the CLI identification string. Generic Anthropic-format providers
    (app/providers/anthropic_compatible.py) reuse this conversion with prefix None."""
    system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system_prefix}] if system_prefix else []
    messages: list[dict[str, Any]] = []
    pending_tool_results: list[dict[str, Any]] = []

    def flush_tool_results() -> None:
        if pending_tool_results:
            messages.append({"role": "user", "content": list(pending_tool_results)})
            pending_tool_results.clear()

    for message in chat_payload.get("messages", []):
        role = message.get("role", "user")
        if role == "system":
            text = _text_of(message.get("content"))
            if text:
                system_blocks.append({"type": "text", "text": text})
            continue
        if role == "tool":
            pending_tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": message.get("tool_call_id") or "",
                    "content": _text_of(message.get("content")),
                }
            )
            continue
        flush_tool_results()
        if role == "assistant" and message.get("tool_calls"):
            blocks = _content_blocks(message.get("content"))
            for call in message["tool_calls"]:
                function = (call or {}).get("function") or {}
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except Exception:
                    args = {}
                blocks.append({"type": "tool_use", "id": call.get("id") or "", "name": function.get("name") or "", "input": args})
            messages.append({"role": "assistant", "content": blocks})
            continue
        anthropic_role = "assistant" if role == "assistant" else "user"
        blocks = _content_blocks(message.get("content")) or [{"type": "text", "text": ""}]
        messages.append({"role": anthropic_role, "content": blocks})
    flush_tool_results()

    request: dict[str, Any] = {
        "model": model_id,
        "max_tokens": chat_payload.get("max_tokens") or DEFAULT_MAX_TOKENS,
        "messages": messages,
    }
    if system_blocks:
        request["system"] = system_blocks

    temperature = chat_payload.get("temperature")
    # Opus 4.8 rejects the parameter instead of accepting the usual 0..1
    # range, so omit it even when an OpenAI-compatible client sends a value.
    if temperature is not None and not model_id.startswith("claude-opus-4-8"):
        request["temperature"] = max(0.0, min(1.0, float(temperature)))

    tools = [
        {
            "name": (tool.get("function") or {}).get("name") or "",
            "description": (tool.get("function") or {}).get("description") or "",
            "input_schema": (tool.get("function") or {}).get("parameters") or {"type": "object", "properties": {}},
        }
        for tool in chat_payload.get("tools") or []
        if isinstance(tool, dict) and tool.get("type") == "function"
    ]
    if tools:
        request["tools"] = tools

    if chat_payload.get("stream"):
        request["stream"] = True
    return request


def _usage_from_message(usage: dict[str, Any]) -> dict[str, int]:
    prompt = int(usage.get("input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0)
    completion = int(usage.get("output_tokens") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


def fold_message_to_completion(body: dict[str, Any], model_id: str) -> tuple[int, dict[str, Any]]:
    """Messages API response -> chat.completion."""
    text_chunks: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for block in body.get("content") or []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text_chunks.append(block.get("text", ""))
        elif block.get("type") == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id") or f"call_{uuid.uuid4().hex[:24]}",
                    "type": "function",
                    "function": {"name": block.get("name") or "", "arguments": json.dumps(block.get("input") or {})},
                }
            )
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text_chunks) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    finish = STOP_REASON_MAP.get(body.get("stop_reason") or "end_turn", "stop")
    return 200, {
        "id": body.get("id") or f"claude-code-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": _usage_from_message(body.get("usage") or {}),
    }


def iter_sse_events(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if not data:
            continue
        try:
            event = json.loads(data)
        except Exception:
            continue
        if isinstance(event, dict):
            yield event


def _chunk(model_id: str, completion_id: str, delta: dict[str, Any], finish: str | None = None, usage: dict[str, int] | None = None) -> bytes:
    body: dict[str, Any] = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }
    if usage is not None:
        body["usage"] = usage
    return f"data: {json.dumps(body)}\n\n".encode()


def stream_events_as_chunks(events: Iterable[dict[str, Any]], model_id: str) -> Iterator[bytes]:
    """Re-emit a Messages API SSE stream as chat.completion.chunk SSE, ending
    with a usage chunk (picked up by the router's usage accounting) and
    [DONE]."""
    completion_id = f"claude-code-{uuid.uuid4()}"
    started = False
    finish = "stop"
    prompt_tokens = 0
    completion_tokens = 0
    tool_index_by_block: dict[int, int] = {}
    tool_count = 0

    for event in events:
        kind = event.get("type")
        if kind == "message_start":
            usage = (event.get("message") or {}).get("usage") or {}
            prompt_tokens = _usage_from_message(usage)["prompt_tokens"]
        elif kind == "content_block_start":
            block = event.get("content_block") or {}
            if block.get("type") == "tool_use":
                index = event.get("index")
                tool_index_by_block[index] = tool_count
                delta: dict[str, Any] = {
                    "tool_calls": [
                        {
                            "index": tool_count,
                            "id": block.get("id") or "",
                            "type": "function",
                            "function": {"name": block.get("name") or "", "arguments": ""},
                        }
                    ]
                }
                if not started:
                    delta["role"] = "assistant"
                    started = True
                tool_count += 1
                finish = "tool_calls"
                yield _chunk(model_id, completion_id, delta)
        elif kind == "content_block_delta":
            delta_event = event.get("delta") or {}
            if delta_event.get("type") == "text_delta" and delta_event.get("text"):
                delta = {"content": delta_event["text"]}
                if not started:
                    delta["role"] = "assistant"
                    started = True
                yield _chunk(model_id, completion_id, delta)
            elif delta_event.get("type") == "input_json_delta":
                tool_index = tool_index_by_block.get(event.get("index"), 0)
                yield _chunk(model_id, completion_id, {"tool_calls": [{"index": tool_index, "function": {"arguments": delta_event.get("partial_json") or ""}}]})
        elif kind == "message_delta":
            usage = event.get("usage") or {}
            if "output_tokens" in usage:
                completion_tokens = int(usage.get("output_tokens") or 0)
            stop_reason = (event.get("delta") or {}).get("stop_reason")
            if stop_reason and finish != "tool_calls":
                finish = STOP_REASON_MAP.get(stop_reason, "stop")
        elif kind == "error":
            error = event.get("error") or {}
            yield _chunk(model_id, completion_id, {"content": f"\n[claude-code error: {error.get('message') or 'response failed'}]"})

    usage = {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": prompt_tokens + completion_tokens}
    yield _chunk(model_id, completion_id, {}, finish=finish, usage=usage)
    yield b"data: [DONE]\n\n"


def claude_code_chat_completion(model: ProviderModel, chat_payload: dict[str, Any], timeout: float = 120.0) -> tuple[int, Any]:
    """Adapter entry point, mirroring openai_compatible.chat_completion's contract:
    (status, dict) for non-stream calls, (status, bytes-iterator) for stream."""
    token = claude_code_token(model.api_key or "", model.api_key_env or "")
    if not token:
        return 401, {
            "error": {
                "message": "Claude Code CLI not logged in on this server (~/.claude/.credentials.json missing)",
                "type": "claude_code_auth_error",
            }
        }

    url = claude_code_messages_url(model.base_url)
    request_body = build_messages_request(chat_payload, model.provider_model)
    headers = claude_code_headers(token, getattr(model, "extra_headers", None))

    client = httpx.Client(timeout=timeout)
    try:
        request = client.build_request("POST", url, headers=headers, json=request_body)
        response = client.send(request, stream=True)
    except Exception:
        client.close()
        raise

    if response.status_code >= 400:
        try:
            response.read()
            body = response.json()
        except Exception:
            body = {"error": {"message": (response.text or f"http_{response.status_code}")[:500], "type": "claude_code_http_error"}}
        response.close()
        client.close()
        return response.status_code, body

    if chat_payload.get("stream"):
        def chunk_generator() -> Iterator[bytes]:
            try:
                yield from stream_events_as_chunks(iter_sse_events(response.iter_lines()), model.id)
            finally:
                response.close()
                client.close()

        return response.status_code, chunk_generator()

    try:
        response.read()
        body = response.json()
    finally:
        response.close()
        client.close()
    return fold_message_to_completion(body, model.id)
