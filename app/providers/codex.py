"""OpenAI Codex (ChatGPT Plus/Pro coding plan) protocol adapter.

The Codex backend (chatgpt.com/backend-api/codex) is not OpenAI-compatible:
it authenticates with the OAuth access token from the Codex CLI login
(~/.codex/auth.json -> tokens.access_token) plus a chatgpt-account-id header,
and it speaks the *streaming-only* Responses API. This module translates
chat-completions requests into Responses payloads and folds (or re-emits) the
SSE event stream back as chat completions, so the rest of ForgeRouter treats
Codex like any other provider. The account id is extracted from the token's
JWT claims — the operator only stores the access token.
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from typing import Any, Iterable, Iterator

import httpx

from app.registry import ProviderModel

CODEX_BASE_MARKER = "chatgpt.com/backend-api/codex"
OPENAI_BASE_URL_ENVS = ("OPENAI_BASE_URL", "OpenAI_BASE_URL")

# Static fallback when the Codex CLI models cache is unavailable — the backend has
# no /models endpoint and rejects ids outside the account's plan.
CODEX_MODELS: list[dict[str, Any]] = [
    {"id": "gpt-5.5", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gpt-5.4", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gpt-5.4-mini", "capabilities": ["text", "code", "reasoning", "tool_call"]},
]


def configured_openai_base_url() -> str:
    for name in OPENAI_BASE_URL_ENVS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def is_codex_base_url(base_url: str | None) -> bool:
    value = (base_url or "").rstrip("/")
    return CODEX_BASE_MARKER in value


def codex_responses_url(base_url: str) -> str:
    base = (configured_openai_base_url() or base_url).rstrip("/")
    if CODEX_BASE_MARKER in base or base.endswith("/v1"):
        return base + "/responses"
    return base + "/v1/responses"


CODEX_AUTH_FILE = os.environ.get("CODEX_AUTH_FILE", os.path.expanduser("~/.codex/auth.json"))


def _auth_file_tokens() -> dict[str, Any]:
    try:
        with open(CODEX_AUTH_FILE, encoding="utf-8") as fh:
            return json.load(fh).get("tokens") or {}
    except Exception:
        return {}


def codex_discover_models() -> list[dict[str, Any]]:
    """Model catalog for the plan: the Codex CLI keeps ~/.codex/models_cache.json
    fresh with the models the account may use — read it, fall back to the static
    list. The health scan still decides which ones actually work."""
    try:
        cache_path = os.path.join(os.path.dirname(CODEX_AUTH_FILE), "models_cache.json")
        with open(cache_path, encoding="utf-8") as fh:
            cache = json.load(fh)
        models = [
            {
                "id": str(entry["slug"]),
                "capabilities": ["text", "code", "reasoning", "tool_call"] + ([] if "mini" in str(entry["slug"]) else ["vision"]),
            }
            for entry in cache.get("models") or []
            if isinstance(entry, dict) and entry.get("slug") and entry.get("visibility") == "list"
        ]
        if models:
            return models
    except Exception:
        pass
    return [dict(model) for model in CODEX_MODELS]


def codex_token(api_key: str = "", api_key_env: str = "") -> str:
    """Codex credential resolution: stored key -> env var -> the Codex CLI login
    (~/.codex/auth.json). With the CLI logged in on this machine nothing needs to
    be stored, and the token stays fresh as the CLI refreshes it."""
    if api_key:
        return api_key
    if api_key_env and os.environ.get(api_key_env):
        return os.environ[api_key_env]
    return str(_auth_file_tokens().get("access_token") or "")


def account_id_from_token(token: str) -> str:
    """The chatgpt-account-id header value lives inside the OAuth access token
    (JWT claim https://api.openai.com/auth -> chatgpt_account_id)."""
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        auth_claim = claims.get("https://api.openai.com/auth") or {}
        return str(auth_claim.get("chatgpt_account_id") or "")
    except Exception:
        return ""


def codex_headers(model: ProviderModel) -> dict[str, str]:
    token = codex_token(model.api_key or "", model.api_key_env or "")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "OpenAI-Beta": "responses=experimental",
        "originator": "codex_cli_rs",
        "session_id": str(uuid.uuid4()),
    }
    headers.update(getattr(model, "extra_headers", None) or {})
    if not any(key.lower() == "chatgpt-account-id" for key in headers):
        account_id = str(_auth_file_tokens().get("account_id") or "") or account_id_from_token(token)
        if account_id:
            headers["chatgpt-account-id"] = account_id
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


def _message_parts(content: Any, role: str) -> list[dict[str, Any]]:
    kind = "output_text" if role == "assistant" else "input_text"
    if isinstance(content, str) or content is None:
        return [{"type": kind, "text": content or ""}]
    parts: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            parts.append({"type": kind, "text": part.get("text", "")})
        elif part.get("type") == "image_url":
            parts.append({"type": "input_image", "image_url": (part.get("image_url") or {}).get("url", "")})
    return parts or [{"type": kind, "text": ""}]


def build_responses_payload(chat_payload: dict[str, Any]) -> dict[str, Any]:
    """chat-completions request -> Codex Responses request. The backend rejects
    sampling knobs (temperature/max_tokens), so they are dropped; system
    messages become instructions; tool traffic maps to function_call items."""
    instructions: list[str] = []
    input_items: list[dict[str, Any]] = []
    for message in chat_payload.get("messages", []):
        role = message.get("role", "user")
        if role == "system":
            instructions.append(_text_of(message.get("content")))
            continue
        if role == "tool":
            input_items.append(
                {"type": "function_call_output", "call_id": message.get("tool_call_id") or "", "output": _text_of(message.get("content"))}
            )
            continue
        if role == "assistant" and message.get("tool_calls"):
            text = _text_of(message.get("content"))
            if text:
                input_items.append({"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]})
            for call in message["tool_calls"]:
                function = (call or {}).get("function") or {}
                input_items.append(
                    {
                        "type": "function_call",
                        "call_id": call.get("id") or "",
                        "name": function.get("name") or "",
                        "arguments": function.get("arguments") or "{}",
                    }
                )
            continue
        input_items.append({"type": "message", "role": role, "content": _message_parts(message.get("content"), role)})
    payload: dict[str, Any] = {
        "model": chat_payload.get("model"),
        "instructions": "\n\n".join(filter(None, instructions)) or "You are a helpful assistant.",
        "input": input_items,
        "store": False,
        "stream": True,  # the Codex backend only streams
        "include": [],
    }
    tools = [
        {
            "type": "function",
            "name": (tool.get("function") or {}).get("name") or "",
            "description": (tool.get("function") or {}).get("description") or "",
            "strict": False,
            "parameters": (tool.get("function") or {}).get("parameters") or {"type": "object", "properties": {}},
        }
        for tool in chat_payload.get("tools") or []
        if isinstance(tool, dict) and tool.get("type") == "function"
    ]
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
        payload["parallel_tool_calls"] = False
    return payload


def iter_sse_events(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[len("data:"):].strip()
        if not data or data == "[DONE]":
            continue
        try:
            event = json.loads(data)
        except Exception:
            continue
        if isinstance(event, dict):
            yield event


def _usage_from_response(response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage") or {}
    prompt = int(usage.get("input_tokens") or 0)
    completion = int(usage.get("output_tokens") or 0)
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": int(usage.get("total_tokens") or (prompt + completion)),
    }


def fold_events_to_completion(events: Iterable[dict[str, Any]], model_id: str) -> tuple[int, dict[str, Any]]:
    """Aggregate a Responses SSE event stream into one chat.completion body."""
    text_parts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    response_id = ""
    error_message: str | None = None
    for event in events:
        kind = event.get("type")
        if kind == "response.output_text.delta":
            text_parts.append(str(event.get("delta") or ""))
        elif kind == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                tool_calls.append(
                    {
                        "id": item.get("call_id") or item.get("id") or f"call_{len(tool_calls)}",
                        "type": "function",
                        "function": {"name": item.get("name") or "", "arguments": item.get("arguments") or "{}"},
                    }
                )
        elif kind == "response.completed":
            response = event.get("response") or {}
            response_id = response.get("id") or response_id
            usage = _usage_from_response(response)
        elif kind in ("response.failed", "error"):
            response = event.get("response") or {}
            error = (response.get("error") or {}) if response else (event.get("error") or {})
            error_message = error.get("message") or event.get("message") or "codex_response_failed"
    if error_message:
        return 502, {"error": {"message": error_message, "type": "codex_response_failed"}}
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return 200, {
        "id": response_id or f"codex-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
        "usage": usage,
    }


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
    """Re-emit a Responses SSE event stream as chat.completion.chunk SSE, ending
    with a usage chunk (picked up by the router's usage accounting) and [DONE]."""
    completion_id = f"codex-{uuid.uuid4()}"
    started = False
    tool_call_count = 0
    finish = "stop"
    usage: dict[str, int] | None = None
    for event in events:
        kind = event.get("type")
        if kind == "response.output_text.delta":
            delta: dict[str, Any] = {"content": str(event.get("delta") or "")}
            if not started:
                delta["role"] = "assistant"
                started = True
            yield _chunk(model_id, completion_id, delta)
        elif kind == "response.output_item.done":
            item = event.get("item") or {}
            if item.get("type") == "function_call":
                delta = {
                    "tool_calls": [
                        {
                            "index": tool_call_count,
                            "id": item.get("call_id") or item.get("id") or f"call_{tool_call_count}",
                            "type": "function",
                            "function": {"name": item.get("name") or "", "arguments": item.get("arguments") or "{}"},
                        }
                    ]
                }
                if not started:
                    delta["role"] = "assistant"
                    started = True
                tool_call_count += 1
                finish = "tool_calls"
                yield _chunk(model_id, completion_id, delta)
        elif kind == "response.completed":
            usage = _usage_from_response(event.get("response") or {})
        elif kind in ("response.failed", "error"):
            response = event.get("response") or {}
            error = (response.get("error") or {}) if response else (event.get("error") or {})
            yield _chunk(model_id, completion_id, {"content": f"\n[codex error: {error.get('message') or 'response failed'}]"})
    yield _chunk(model_id, completion_id, {}, finish=finish, usage=usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    yield b"data: [DONE]\n\n"


def codex_chat_completion(model: ProviderModel, chat_payload: dict[str, Any], timeout: float = 120.0) -> tuple[int, Any]:
    """Adapter entry point, mirroring openai_compatible.chat_completion's contract:
    (status, dict) for non-stream calls, (status, bytes-iterator) for stream."""
    url = codex_responses_url(model.base_url)
    payload = build_responses_payload(chat_payload)
    client = httpx.Client(timeout=timeout)
    try:
        request = client.build_request("POST", url, headers=codex_headers(model), json=payload)
        response = client.send(request, stream=True)
    except Exception:
        client.close()
        raise
    if response.status_code >= 400:
        try:
            response.read()
            body = response.json()
        except Exception:
            body = {"error": {"message": (response.text or f"http_{response.status_code}")[:500], "type": "codex_http_error"}}
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
        return fold_events_to_completion(iter_sse_events(response.iter_lines()), model.id)
    finally:
        response.close()
        client.close()
