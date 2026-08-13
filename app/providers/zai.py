"""Z.ai web subscription adapter.

ForgeRouter implements the same concept as zai-proxy without importing that
project's code: it uses the Z.ai web chat API, supports the anonymous free token
flow, signs requests, and translates the upstream SSE stream into
OpenAI-compatible chat completions.

Supported auth file shapes:
- {"access_token": "..."}
- {"token": "..."}
- {"token": {"access_token": "..."}}
- {"tokens": {"access_token": "..."}}
- {"oauth": {"access_token": "..."}}
"""

from __future__ import annotations

import json
import os
import time
import uuid
import hmac
import hashlib
import base64
from typing import Any, Iterator

import httpx

from app.registry import ProviderModel

ZAI_BASE_MARKERS = ("chat.z.ai/api", "api.z.ai/api/coding/paas/v4")
ZAI_AUTH_FILE = os.environ.get("ZAI_AUTH_FILE", os.path.expanduser("~/.zai/auth.json"))
ZAI_CHAT_BASE = "https://chat.z.ai/api"
ZAI_MODELS: list[dict[str, Any]] = [
    {"id": "glm-4.5", "capabilities": ["text"]},
    {"id": "glm-4.6", "capabilities": ["text"]},
    {"id": "glm-4.7", "capabilities": ["text"]},
    {"id": "glm-4.7-thinking", "capabilities": ["text", "reasoning"]},
    {"id": "glm-4.7-thinking-search", "capabilities": ["text", "reasoning"]},
    {"id": "glm-4.7-tools", "capabilities": ["text", "tool_call"]},
    {"id": "glm-4.7-tools-thinking", "capabilities": ["text", "tool_call", "reasoning"]},
    {"id": "glm-5", "capabilities": ["text"]},
    {"id": "glm-5-thinking", "capabilities": ["text", "reasoning"]},
    {"id": "glm-5-tools", "capabilities": ["text", "tool_call"]},
    {"id": "glm-4.5-v", "capabilities": ["text", "vision"]},
    {"id": "glm-4.6-v", "capabilities": ["text", "vision"]},
    {"id": "glm-4.5-air", "capabilities": ["text"]},
]
ZAI_TARGET_MODELS = {
    "glm-4.5": "0727-360B-API",
    "glm-4.6": "GLM-4-6-API-V1",
    "glm-4.7": "glm-4.7",
    "glm-5": "glm-5",
    "glm-4.5-v": "glm-4.5v",
    "glm-4.6-v": "glm-4.6v",
    "glm-4.5-air": "0727-106B-API",
}
_ANON_TOKEN = ""
_FE_VERSION = ""


def is_zai_base_url(base_url: str | None) -> bool:
    return any(marker in (base_url or "") for marker in ZAI_BASE_MARKERS)


def zai_discover_models() -> list[dict[str, Any]]:
    return [dict(model) for model in ZAI_MODELS]


def _read_auth_file() -> dict[str, Any]:
    try:
        with open(ZAI_AUTH_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _nested_token(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if isinstance(value, dict):
        return str(value.get("access_token") or value.get("token") or "")
    return ""


def zai_token(api_key: str = "", api_key_env: str = "") -> str:
    """Credential order: explicit token -> env var -> local file -> anonymous."""
    if api_key and api_key != "free":
        return api_key
    if api_key_env and os.environ.get(api_key_env):
        return os.environ[api_key_env]
    data = _read_auth_file()
    return str(
        data.get("access_token")
        or data.get("token")
        or _nested_token(data, "tokens")
        or _nested_token(data, "oauth")
        or _nested_token(data, "session")
        or _anonymous_token()
    )


def _anonymous_token() -> str:
    global _ANON_TOKEN
    if _ANON_TOKEN:
        return _ANON_TOKEN
    try:
        response = httpx.get("https://chat.z.ai/api/v1/auths/", timeout=30.0)
        response.raise_for_status()
        _ANON_TOKEN = str((response.json() or {}).get("token") or "")
    except Exception:
        _ANON_TOKEN = ""
    return _ANON_TOKEN


def _jwt_user_id(token: str) -> str:
    try:
        payload = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        return str(claims.get("id") or "")
    except Exception:
        return ""


def _fe_version() -> str:
    global _FE_VERSION
    if _FE_VERSION:
        return _FE_VERSION
    try:
        import re

        text = httpx.get("https://chat.z.ai/", timeout=10.0).text
        match = re.search(r"prod-fe-[.\d]+", text)
        _FE_VERSION = match.group(0) if match else ""
    except Exception:
        _FE_VERSION = ""
    return _FE_VERSION


def _signature(user_id: str, request_id: str, user_content: str, timestamp: int) -> str:
    request_info = f"requestId,{request_id},timestamp,{timestamp},user_id,{user_id}"
    content_b64 = base64.b64encode(user_content.encode()).decode()
    sign_data = f"{request_info}|{content_b64}|{timestamp}"
    period = timestamp // (5 * 60 * 1000)
    first = hmac.new(b"key-@@@@)))()((9))-xxxx&&&%%%%%", str(period).encode(), hashlib.sha256).hexdigest()
    return hmac.new(first.encode(), sign_data.encode(), hashlib.sha256).hexdigest()


def _parse_model(name: str) -> tuple[str, bool, bool]:
    model = name.lower()
    thinking = "-thinking" in model
    search = "-search" in model
    for suffix in ("-thinking", "-search", "-tools"):
        model = model.replace(suffix, "")
    return ZAI_TARGET_MODELS.get(model, "glm-4.7"), thinking, search


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text")
    return "" if content is None else str(content)


def _messages_for_upstream(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    out: list[dict[str, Any]] = []
    latest_user = ""
    system: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        text = _text_of(message.get("content"))
        if role == "system":
            if text:
                system.append(text)
            continue
        if role == "user" and text:
            latest_user = text
        out.append({"role": role, "content": text})
    if system:
        out = [
            {"role": "user", "content": "[System Instructions]\n" + "\n\n".join(system)},
            {"role": "assistant", "content": "Understood. I will follow these instructions."},
        ] + out
    return out, latest_user


def _chunk(model_id: str, content: str = "", finish: str | None = None, usage: dict[str, Any] | None = None) -> bytes:
    body: dict[str, Any] = {
        "id": f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "delta": {"content": content} if content else {}, "finish_reason": finish}],
    }
    if usage:
        body["usage"] = usage
    return f"data: {json.dumps(body, separators=(',', ':'))}\n\n".encode()


def _completion(model_id: str, content: str) -> dict[str, Any]:
    return {
        "id": f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _error(message: str, code: str = "zai_error", status: int = 502) -> tuple[int, dict[str, Any]]:
    return status, {"error": {"message": message, "type": code, "code": code}}


def _upstream_request(model: ProviderModel, payload: dict[str, Any], token: str) -> tuple[httpx.Client, httpx.Response, str]:
    user_id = _jwt_user_id(token)
    if not user_id:
        raise RuntimeError("invalid_zai_token")
    timestamp = int(time.time() * 1000)
    request_id = str(uuid.uuid4())
    chat_id = str(uuid.uuid4())
    upstream_model, thinking, search = _parse_model(model.provider_model)
    messages, latest_user = _messages_for_upstream(payload.get("messages") or [])
    signature = _signature(user_id, request_id, latest_user, timestamp)
    url = (
        f"https://chat.z.ai/api/v2/chat/completions?timestamp={timestamp}&requestId={request_id}"
        f"&user_id={user_id}&version=0.0.1&platform=web&token={token}"
        f"&current_url=https://chat.z.ai/c/{chat_id}&pathname=/c/{chat_id}&signature_timestamp={timestamp}"
    )
    body = {
        "stream": True,
        "model": upstream_model,
        "messages": messages,
        "signature_prompt": latest_user,
        "params": {},
        "features": {"image_generation": False, "web_search": False, "auto_web_search": search, "preview_mode": True, "enable_thinking": thinking},
        "chat_id": chat_id,
        "id": str(uuid.uuid4()),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-FE-Version": _fe_version(),
        "X-Signature": signature,
        "Content-Type": "application/json",
        "Origin": "https://chat.z.ai",
        "Referer": f"https://chat.z.ai/c/{chat_id}",
        "User-Agent": "Mozilla/5.0",
    }
    client = httpx.Client(timeout=120.0)
    request = client.build_request("POST", url, headers=headers, json=body)
    return client, client.send(request, stream=True), upstream_model


def _iter_upstream_lines(response: httpx.Response) -> Iterator[dict[str, Any]]:
    for line in response.iter_lines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            parsed = json.loads(data)
        except Exception:
            continue
        if isinstance(parsed, dict):
            yield parsed


def _delta(parsed: dict[str, Any]) -> tuple[str, bool]:
    if error := _event_error(parsed):
        message = str(error.get("detail") or error.get("message") or error.get("code") or "Z.ai upstream error")
        code = str(error.get("error_code") or error.get("code") or "zai_upstream_error")
        raise RuntimeError(f"{code}: {message}")
    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
    if isinstance(data.get("data"), dict):
        nested = data["data"]
        if nested.get("phase") == "done" or nested.get("done") is True:
            return "", True
        return str(nested.get("delta_content") or nested.get("edit_content") or ""), False
    if data.get("phase") == "done" or data.get("done") is True:
        return "", True
    return str(data.get("delta_content") or data.get("edit_content") or ""), False


def _event_error(parsed: dict[str, Any]) -> dict[str, Any] | None:
    candidates: list[Any] = [parsed]
    data = parsed.get("data")
    if isinstance(data, dict):
        candidates.append(data)
        if isinstance(data.get("data"), dict):
            candidates.append(data["data"])
    for candidate in candidates:
        if isinstance(candidate, dict) and isinstance(candidate.get("error"), dict):
            return candidate["error"]
    return None


ZAI_PAID_API_MARKER = "api.z.ai/api/coding/paas/v4"


def _paid_api_chat_completion(model: ProviderModel, payload: dict[str, Any], timeout: float) -> tuple[int, Any]:
    """The paid api.z.ai/api/coding/paas/v4 surface is plain OpenAI-compatible —
    unlike the free chat.z.ai web adapter below, no signing/session dance, just
    a bearer API key. Kept self-contained (not delegated to
    openai_compatible.chat_completion) since that function dispatches back
    through plan_for(), which would route straight back here."""
    token = zai_token(model.api_key or "", model.api_key_env or "")
    if not token:
        return 401, {"error": {"message": "Z.ai API key unavailable", "type": "missing_credentials"}}
    url = model.base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {token}"}
    body = {**payload, "model": model.provider_model}
    if payload.get("stream"):
        client = httpx.Client(timeout=timeout)
        try:
            request = client.build_request("POST", url, headers=headers, json=body)
            response = client.send(request, stream=True)
        except Exception:
            client.close()
            raise
        if response.status_code >= 400:
            response.read()
            try:
                err_body = response.json()
            except Exception:
                err_body = {"error": {"message": response.text, "type": "zai_http_error"}}
            response.close()
            client.close()
            return response.status_code, err_body

        def chunk_generator() -> Iterator[bytes]:
            try:
                for chunk in response.iter_bytes():
                    yield chunk
            finally:
                response.close()
                client.close()

        return response.status_code, chunk_generator()

    response = httpx.post(url, headers=headers, json=body, timeout=timeout)
    try:
        resp_body = response.json()
    except Exception:
        resp_body = {"error": {"message": response.text, "type": "zai_http_error"}}
    return response.status_code, resp_body


def zai_chat_completion(model: ProviderModel, payload: dict[str, Any], timeout: float = 60.0) -> tuple[int, Any]:
    if ZAI_PAID_API_MARKER in (model.base_url or ""):
        return _paid_api_chat_completion(model, payload, timeout=timeout)
    token = zai_token(model.api_key or "", model.api_key_env or "")
    if not token:
        return 401, {"error": {"message": "Z.ai token unavailable", "type": "missing_credentials"}}
    try:
        client, upstream, upstream_model = _upstream_request(model, payload, token)
    except Exception as exc:
        return 502, {"error": {"message": str(exc), "type": "zai_request_failed"}}
    if upstream.status_code >= 400:
        upstream.read()
        text = upstream.text
        upstream.close()
        client.close()
        return upstream.status_code, {"error": {"message": text, "type": "zai_http_error"}}
    if payload.get("stream"):
        def chunks() -> Iterator[bytes]:
            try:
                for parsed in _iter_upstream_lines(upstream):
                    try:
                        text, done = _delta(parsed)
                    except RuntimeError as exc:
                        # In-band error chunk (OpenRouter-style): the router's
                        # _error_from_sse_line treats it as a provider failure —
                        # unhealthy mark + provider_error route event — instead of
                        # a clean stop recorded as success.
                        yield f'data: {json.dumps({"error": {"message": str(exc), "code": "zai_upstream_error"}})}\n\n'.encode()
                        break
                    if text:
                        yield _chunk(model.id, text)
                    if done:
                        yield _chunk(model.id, "", "stop")
                        yield b"data: [DONE]\n\n"
                        break
            finally:
                upstream.close()
                client.close()
        return 200, chunks()
    parts: list[str] = []
    try:
        for parsed in _iter_upstream_lines(upstream):
            try:
                text, done = _delta(parsed)
            except RuntimeError as exc:
                return _error(str(exc), "zai_upstream_error")
            if text:
                parts.append(text)
            if done:
                break
    finally:
        upstream.close()
        client.close()
    return 200, _completion(model.id or upstream_model, "".join(parts))
