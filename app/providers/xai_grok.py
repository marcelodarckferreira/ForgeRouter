"""xAI Grok (SuperGrok / X Premium+ subscription) protocol adapter.

OAuth-authenticated Grok access does not go through the public, api-key-billed
`api.x.ai/v1` surface — it rides a dedicated proxy, `cli-chat-proxy.grok.com/v1`,
speaking the same streaming-only OpenAI Responses API shape Codex uses (see
`app/providers/codex.py`, whose payload/event-folding logic this module mirrors).
Unlike every other subscription adapter in this codebase, there is no existing
CLI (`claude`, `codex`, `agy`) already logged in on the host to keep the token
fresh — `scripts/xai_oauth_login.py` performs the initial OAuth 2.0 device-code
login, and this module refreshes the access token itself before it expires
(reading/rewriting `~/.xai/auth.json`), instead of relying on an external
process the way the other adapters do.

Endpoints and the client_id come from the reference OAuth implementation the
xAI ecosystem converged on (Hermes Agent's `xai-oauth`, and downstream tools
like `pi-grok`, `opencode-grok-auth`) — xAI does not publish first-party OAuth
docs for third-party clients. Standard SuperGrok subscribers have been
reported to receive `403` on this OAuth surface despite an active
subscription (an xAI-side allowlist, not something this client controls); if
that happens here, fall back to a plain `XAI_API_KEY` provider instead.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Iterable, Iterator

import httpx

from app.registry import ProviderModel

XAI_BASE_MARKER = "cli-chat-proxy.grok.com"
XAI_CLI_PROXY_BASE = "https://cli-chat-proxy.grok.com/v1"
XAI_ISSUER = "https://auth.x.ai"
XAI_DEVICE_CODE_URL = f"{XAI_ISSUER}/oauth2/device/code"
XAI_TOKEN_URL = f"{XAI_ISSUER}/oauth2/token"
XAI_DEVICE_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"
XAI_CLIENT_ID = os.environ.get("XAI_OAUTH_CLIENT_ID", "b1a00492-073a-47ea-816f-4c329264a828")
XAI_SCOPE = os.environ.get(
    "XAI_OAUTH_SCOPE",
    "openid profile email offline_access grok-cli:access api:access conversations:read conversations:write",
)
XAI_CLIENT_VERSION = os.environ.get("XAI_CLIENT_VERSION", "0.2.101")
XAI_CLIENT_IDENTIFIER = os.environ.get("XAI_CLIENT_IDENTIFIER", "grok-shell")
# Refresh this long before the real expiry so a request never races a token
# that is about to lapse mid-flight.
XAI_REFRESH_SKEW_SECONDS = 300

XAI_AUTH_FILE = os.environ.get("XAI_AUTH_FILE", os.path.expanduser("~/.xai/auth.json"))

# Static fallback catalog — mirrors the reference clients' hardcoded list;
# there is no /models endpoint on the CLI proxy for this account tier. The
# health scan decides which of these actually work for the account.
XAI_MODELS: list[dict[str, Any]] = [
    {"id": "grok-composer-2.5-fast", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "grok-build", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "grok-4.5", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "grok-4.3", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "grok-4.20-0309-reasoning", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "grok-4.20-0309-non-reasoning", "capabilities": ["text", "code", "tool_call", "vision"]},
    {"id": "grok-4.20-multi-agent-0309", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
]


def is_xai_grok_base_url(base_url: str | None) -> bool:
    return XAI_BASE_MARKER in (base_url or "")


def xai_grok_responses_url(base_url: str) -> str:
    base = (base_url or XAI_CLI_PROXY_BASE).rstrip("/")
    return base + "/responses"


def xai_grok_discover_models() -> list[dict[str, Any]]:
    return [dict(model) for model in XAI_MODELS]


def _auth_file() -> dict[str, Any]:
    try:
        with open(XAI_AUTH_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_auth_file(data: dict[str, Any]) -> None:
    # Best-effort: a failed write just means the next call refreshes again —
    # the in-memory token this call already has still works for this request.
    try:
        os.makedirs(os.path.dirname(XAI_AUTH_FILE), exist_ok=True)
        tmp_path = XAI_AUTH_FILE + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        os.replace(tmp_path, XAI_AUTH_FILE)
    except Exception:
        pass


def _refresh(auth: dict[str, Any]) -> dict[str, Any]:
    refresh_token = auth.get("refresh_token")
    if not refresh_token:
        return {}
    token_url = auth.get("token_endpoint") or XAI_TOKEN_URL
    try:
        response = httpx.post(
            token_url,
            data={"grant_type": "refresh_token", "client_id": XAI_CLIENT_ID, "refresh_token": refresh_token},
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
            timeout=15.0,
        )
        response.raise_for_status()
        body = response.json()
    except Exception:
        return {}
    access_token = body.get("access_token")
    if not access_token:
        return {}
    updated = {
        **auth,
        "access_token": access_token,
        "refresh_token": body.get("refresh_token") or refresh_token,
        "expires_at": time.time() + float(body.get("expires_in") or 3600) - XAI_REFRESH_SKEW_SECONDS,
        "token_endpoint": token_url,
    }
    _write_auth_file(updated)
    return updated


def xai_grok_token(api_key: str = "", api_key_env: str = "") -> str:
    """Credential resolution: stored key -> env var -> ~/.xai/auth.json, refreshing
    it in place when it's expired (or close to it) since no external CLI does that
    for this provider the way it does for Claude Code/Codex/Antigravity."""
    if api_key:
        return api_key
    if api_key_env and os.environ.get(api_key_env):
        return os.environ[api_key_env]
    auth = _auth_file()
    access_token = str(auth.get("access_token") or "")
    expires_at = float(auth.get("expires_at") or 0)
    if not access_token or time.time() >= expires_at:
        refreshed = _refresh(auth)
        access_token = str(refreshed.get("access_token") or access_token)
    return access_token


def xai_grok_headers(model: ProviderModel) -> dict[str, str]:
    token = xai_grok_token(model.api_key or "", model.api_key_env or "")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "User-Agent": f"{XAI_CLIENT_IDENTIFIER}/{XAI_CLIENT_VERSION} (linux; x86_64)",
        "x-grok-client-identifier": XAI_CLIENT_IDENTIFIER,
        "x-grok-client-version": XAI_CLIENT_VERSION,
        "x-grok-client-mode": "interactive",
        "X-XAI-Token-Auth": "xai-grok-cli",
        "x-authenticateresponse": "authenticate-response",
        "x-grok-model-override": model.provider_model or model.id,
    }
    headers.update(getattr(model, "extra_headers", None) or {})
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
    """chat-completions request -> Responses API request for the Grok CLI proxy."""
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
        "stream": True,  # the proxy only streams
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
            error_message = error.get("message") or event.get("message") or "xai_grok_response_failed"
    if error_message:
        return 502, {"error": {"message": error_message, "type": "xai_grok_response_failed"}}
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text_parts) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return 200, {
        "id": response_id or f"xai-grok-{uuid.uuid4()}",
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
    completion_id = f"xai-grok-{uuid.uuid4()}"
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
            yield _chunk(model_id, completion_id, {"content": f"\n[xai-grok error: {error.get('message') or 'response failed'}]"})
    yield _chunk(model_id, completion_id, {}, finish=finish, usage=usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    yield b"data: [DONE]\n\n"


def xai_grok_chat_completion(model: ProviderModel, chat_payload: dict[str, Any], timeout: float = 120.0) -> tuple[int, Any]:
    """Adapter entry point, mirroring openai_compatible.chat_completion's contract:
    (status, dict) for non-stream calls, (status, bytes-iterator) for stream."""
    url = xai_grok_responses_url(model.base_url)
    payload = build_responses_payload(chat_payload)
    client = httpx.Client(timeout=timeout)
    try:
        request = client.build_request("POST", url, headers=xai_grok_headers(model), json=payload)
        response = client.send(request, stream=True)
    except Exception:
        client.close()
        raise
    if response.status_code >= 400:
        try:
            response.read()
            body = response.json()
        except Exception:
            body = {"error": {"message": (response.text or f"http_{response.status_code}")[:500], "type": "xai_grok_http_error"}}
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
