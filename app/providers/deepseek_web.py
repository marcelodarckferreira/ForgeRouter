"""DeepSeek web subscription adapter.

This is an internal ForgeRouter implementation of the same architectural idea
as ds-free-api, without importing that project's GPL code: login to DeepSeek's
web backend, create a short-lived chat session, solve the DeepSeekHashV1 PoW
challenge with the provider WASM, and translate the SSE stream to an
OpenAI-compatible chat completion.

Credentials are read from DEEPSEEK_* env vars or ~/.deepseek/auth.json. The
auth file may contain either a ready token or login credentials:

{"token": "..."}
{"email": "...", "password": "..."}
{"mobile": "...", "area_code": "+55", "password": "..."}
"""

from __future__ import annotations

import base64
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Iterator

import httpx

from app.registry import ProviderModel

DEEPSEEK_WEB_BASE_MARKER = "chat.deepseek.com/api/v0"
DEEPSEEK_WEB_AUTH_FILE = os.environ.get("DEEPSEEK_WEB_AUTH_FILE", os.path.expanduser("~/.deepseek/auth.json"))
DEEPSEEK_WEB_WASM_URL = os.environ.get("DEEPSEEK_WEB_WASM_URL", "https://fe-static.deepseek.com/chat/static/sha3_wasm_bg.7b9ca65ddd.wasm")
DEEPSEEK_WEB_USER_AGENT = os.environ.get("DEEPSEEK_WEB_USER_AGENT", "DeepSeek/2.1.1 Android/35")
DEEPSEEK_WEB_CLIENT_VERSION = os.environ.get("DEEPSEEK_WEB_CLIENT_VERSION", "2.0.0")
DEEPSEEK_WEB_CLIENT_PLATFORM = os.environ.get("DEEPSEEK_WEB_CLIENT_PLATFORM", "android")
DEEPSEEK_WEB_CLIENT_LOCALE = os.environ.get("DEEPSEEK_WEB_CLIENT_LOCALE", "zh_CN")

DEEPSEEK_WEB_MODELS: list[dict[str, Any]] = [
    {"id": "deepseek-default", "capabilities": ["text"]},
    {"id": "deepseek-expert", "capabilities": ["text", "reasoning", "code"]},
    {"id": "deepseek-vision", "capabilities": ["text", "vision"]},
]

_TOKEN_CACHE: dict[str, str] = {}
_WASM_CACHE: bytes | None = None


def is_deepseek_web_base_url(base_url: str | None) -> bool:
    return DEEPSEEK_WEB_BASE_MARKER in (base_url or "")


def deepseek_web_discover_models() -> list[dict[str, Any]]:
    return [dict(model) for model in DEEPSEEK_WEB_MODELS]


def _auth_file() -> dict[str, Any]:
    try:
        with open(DEEPSEEK_WEB_AUTH_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _base_url(model_or_url: ProviderModel | str) -> str:
    url = model_or_url.base_url if isinstance(model_or_url, ProviderModel) else model_or_url
    return (url or "https://chat.deepseek.com/api/v0").rstrip("/")


def _common_headers(token: str = "") -> dict[str, str]:
    headers = {
        "User-Agent": DEEPSEEK_WEB_USER_AGENT,
        "X-Client-Version": DEEPSEEK_WEB_CLIENT_VERSION,
        "X-Client-Platform": DEEPSEEK_WEB_CLIENT_PLATFORM,
        "X-Client-Locale": DEEPSEEK_WEB_CLIENT_LOCALE,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _unwrap_envelope(body: dict[str, Any]) -> Any:
    if body.get("code") != 0:
        raise RuntimeError(body.get("msg") or f"deepseek_code_{body.get('code')}")
    data = body.get("data") or {}
    if data.get("biz_code") != 0:
        raise RuntimeError(data.get("biz_msg") or f"deepseek_biz_{data.get('biz_code')}")
    return data.get("biz_data")


def _credentials(api_key: str = "", api_key_env: str = "") -> dict[str, Any]:
    if api_key:
        try:
            parsed = json.loads(api_key)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {"token": api_key}
    if api_key_env and os.environ.get(api_key_env):
        return {"token": os.environ[api_key_env]}
    data = _auth_file()
    return {
        "token": data.get("token") or data.get("access_token") or os.environ.get("DEEPSEEK_WEB_TOKEN", ""),
        "email": data.get("email") or os.environ.get("DEEPSEEK_WEB_EMAIL", ""),
        "mobile": data.get("mobile") or os.environ.get("DEEPSEEK_WEB_MOBILE", ""),
        "area_code": data.get("area_code") or os.environ.get("DEEPSEEK_WEB_AREA_CODE", ""),
        "password": data.get("password") or os.environ.get("DEEPSEEK_WEB_PASSWORD", ""),
    }


def deepseek_web_token(api_key: str = "", api_key_env: str = "", base_url: str = "https://chat.deepseek.com/api/v0") -> str:
    creds = _credentials(api_key, api_key_env)
    token = str(creds.get("token") or "")
    if token:
        return token
    cache_key = f"{creds.get('email') or creds.get('mobile')}@{base_url}"
    if _TOKEN_CACHE.get(cache_key):
        return _TOKEN_CACHE[cache_key]
    if not creds.get("password") or not (creds.get("email") or creds.get("mobile")):
        return ""
    payload = {
        "email": creds.get("email") or None,
        "mobile": creds.get("mobile") or None,
        "password": creds["password"],
        "area_code": creds.get("area_code") or None,
        "device_id": "",
        "os": "web",
    }
    response = httpx.post(_base_url(base_url) + "/users/login", headers=_common_headers(), json=payload, timeout=30.0)
    body = response.json()
    if response.status_code >= 400:
        raise RuntimeError(f"deepseek_login_http_{response.status_code}: {response.text}")
    user = (_unwrap_envelope(body) or {}).get("user") or {}
    token = str(user.get("token") or "")
    if token:
        _TOKEN_CACHE[cache_key] = token
    return token


def _create_session(base_url: str, token: str) -> str:
    response = httpx.post(_base_url(base_url) + "/chat_session/create", headers=_common_headers(token), json={}, timeout=30.0)
    wrapper = _unwrap_envelope(response.json()) or {}
    return str((wrapper.get("chat_session") or {}).get("id") or "")


def _delete_session(base_url: str, token: str, session_id: str) -> None:
    try:
        httpx.post(_base_url(base_url) + "/chat_session/delete", headers=_common_headers(token), json={"chat_session_id": session_id}, timeout=10.0)
    except Exception:
        pass


def _pow_challenge(base_url: str, token: str, target_path: str) -> dict[str, Any]:
    response = httpx.post(
        _base_url(base_url) + "/chat/create_pow_challenge",
        headers=_common_headers(token),
        json={"target_path": target_path},
        timeout=30.0,
    )
    wrapper = _unwrap_envelope(response.json()) or {}
    return wrapper.get("challenge") or {}


@dataclass
class _PowResult:
    algorithm: str
    challenge: str
    salt: str
    answer: int
    signature: str
    target_path: str

    def header(self) -> str:
        raw = json.dumps(self.__dict__, separators=(",", ":")).encode()
        return base64.b64encode(raw).decode()


def _wasm_bytes() -> bytes:
    global _WASM_CACHE
    if _WASM_CACHE is None:
        response = httpx.get(DEEPSEEK_WEB_WASM_URL, timeout=30.0)
        response.raise_for_status()
        _WASM_CACHE = response.content
    return _WASM_CACHE


def solve_pow(challenge: dict[str, Any]) -> str:
    if challenge.get("algorithm") != "DeepSeekHashV1":
        raise RuntimeError(f"unsupported_deepseek_pow_{challenge.get('algorithm')}")
    import wasmtime

    store = wasmtime.Store()
    module = wasmtime.Module(store.engine, _wasm_bytes())
    instance = wasmtime.Instance(store, module, [])
    exports = {export.name: export for export in module.exports}

    def func_by_sig(names: list[str], params: list[str], results: list[str]) -> str:
        for name in names:
            export = exports.get(name)
            if export and getattr(export.type, "params", None):
                if [str(item) for item in export.type.params] == params and [str(item) for item in export.type.results] == results:
                    return name
        for name, export in exports.items():
            if names and not any(name.startswith(prefix) for prefix in names if prefix.endswith("_")):
                continue
            typ = getattr(export, "type", None)
            if typ and getattr(typ, "params", None):
                if [str(item) for item in typ.params] == params and [str(item) for item in typ.results] == results:
                    return name
        raise RuntimeError("deepseek_wasm_export_not_found")

    add_name = func_by_sig(["__wbindgen_add_to_stack_pointer"], ["i32"], ["i32"])
    alloc_name = func_by_sig(["__wbindgen_malloc", "__wbindgen_export_"], ["i32", "i32"], ["i32"])
    solve_name = func_by_sig(["wasm_solve"], ["i32", "i32", "i32", "i32", "i32", "f64"], [])
    memory = instance.exports(store)["memory"]
    add_to_stack = instance.exports(store)[add_name]
    alloc = instance.exports(store)[alloc_name]
    wasm_solve = instance.exports(store)[solve_name]

    def write_string(value: str) -> tuple[int, int]:
        data = value.encode()
        ptr = alloc(store, len(data), 1)
        memory.write(store, data, ptr)
        return ptr, len(data)

    retptr = add_to_stack(store, -16)
    ptr_challenge, len_challenge = write_string(str(challenge["challenge"]))
    ptr_prefix, len_prefix = write_string(f"{challenge['salt']}_{challenge['expire_at']}_")
    wasm_solve(store, retptr, ptr_challenge, len_challenge, ptr_prefix, len_prefix, float(challenge["difficulty"]))
    status = int.from_bytes(memory.read(store, retptr, retptr + 4), "little", signed=True)
    value = int.from_bytes(memory.read(store, retptr + 8, retptr + 16), "little", signed=False)
    # The WASM writes an f64 at retptr+8.
    import struct

    answer = int(struct.unpack("<d", value.to_bytes(8, "little"))[0])
    if status == 0:
        raise RuntimeError("deepseek_pow_no_solution")
    return _PowResult(
        algorithm=str(challenge["algorithm"]),
        challenge=str(challenge["challenge"]),
        salt=str(challenge["salt"]),
        answer=answer,
        signature=str(challenge["signature"]),
        target_path=str(challenge["target_path"]),
    ).header()


def _prompt_from_messages(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content")
        if isinstance(content, list):
            text = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict) and part.get("type") == "text")
        else:
            text = "" if content is None else str(content)
        if text:
            parts.append(f"{role}: {text}")
    return "\n\n".join(parts)


class _PatchState:
    def __init__(self) -> None:
        self.path = ""
        self.op = "SET"
        self.usage = 0

    def apply(self, event: dict[str, Any]) -> tuple[str, bool, int]:
        if "p" in event:
            self.path = str(event["p"])
        if "o" in event:
            self.op = str(event["o"])
        value = event.get("v")
        text = ""
        done = False
        if self.op == "BATCH" and isinstance(value, list):
            for item in value:
                sub_text, sub_done, sub_usage = self.apply(item if isinstance(item, dict) else {})
                text += sub_text
                done = done or sub_done
                self.usage = sub_usage or self.usage
            return text, done, self.usage
        if self.path.endswith("/content") and isinstance(value, str):
            text += value
        if self.path in ("response/accumulated_token_usage", "accumulated_token_usage") and isinstance(value, int):
            self.usage = value
        if (self.path.endswith("status") or self.path.endswith("quasi_status")) and value in ("FINISHED", "INCOMPLETE"):
            done = True
        if isinstance(value, dict) and isinstance(value.get("response"), dict):
            response = value["response"]
            self.usage = int(response.get("accumulated_token_usage") or self.usage)
            for frag in response.get("fragments") or []:
                if isinstance(frag, dict) and frag.get("type") == "RESPONSE" and frag.get("content"):
                    text += str(frag["content"])
            done = response.get("status") in ("FINISHED", "INCOMPLETE")
        return text, done, self.usage


def _iter_data_events(lines: Iterable[str]) -> Iterator[dict[str, Any]]:
    for line in lines:
        line = line.strip()
        if not line.startswith("data:"):
            continue
        try:
            parsed = json.loads(line[5:].strip())
        except Exception:
            continue
        if isinstance(parsed, dict):
            yield parsed


def _chat_completion_body(model_id: str, text: str, completion_tokens: int = 0) -> dict[str, Any]:
    return {
        "id": f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": completion_tokens, "total_tokens": completion_tokens},
    }


def _chat_sse_line(model_id: str, content: str = "", finish: str | None = None, usage: dict[str, Any] | None = None) -> bytes:
    body = {
        "id": f"chatcmpl_{uuid.uuid4().hex}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "delta": {"content": content} if content else {}, "finish_reason": finish}],
    }
    if usage:
        body["usage"] = usage
    return f"data: {json.dumps(body, separators=(',', ':'))}\n\n".encode()


def deepseek_web_chat_completion(model: ProviderModel, payload: dict[str, Any], timeout: float = 120.0) -> tuple[int, Any]:
    token = deepseek_web_token(model.api_key or "", model.api_key_env or "", model.base_url)
    if not token:
        return 401, {"error": {"message": "DeepSeek web credentials missing: set ~/.deepseek/auth.json or DEEPSEEK_WEB_* env vars", "type": "missing_credentials"}}
    session_id = _create_session(model.base_url, token)
    if not session_id:
        return 502, {"error": {"message": "DeepSeek session creation failed", "type": "session_failed"}}
    pow_header = solve_pow(_pow_challenge(model.base_url, token, "/api/v0/chat/completion"))
    model_type = model.provider_model.replace("deepseek-", "")
    request = {
        "chat_session_id": session_id,
        "parent_message_id": None,
        "model_type": model_type,
        "prompt": _prompt_from_messages(payload.get("messages") or []),
        "ref_file_ids": [],
        "thinking_enabled": model_type == "expert",
        "search_enabled": False,
        "preempt": False,
    }
    headers = {**_common_headers(token), "X-Ds-Pow-Response": pow_header}
    client = httpx.Client(timeout=timeout)
    response = client.build_request("POST", _base_url(model.base_url) + "/chat/completion", headers=headers, json=request)
    upstream = client.send(response, stream=True)
    if upstream.status_code >= 400:
        text = upstream.text
        upstream.close()
        client.close()
        _delete_session(model.base_url, token, session_id)
        return upstream.status_code, {"error": {"message": text, "type": "deepseek_http_error"}}

    if payload.get("stream"):
        def chunks() -> Iterator[bytes]:
            state = _PatchState()
            try:
                yield _chat_sse_line(model.id, "")
                for event in _iter_data_events(upstream.iter_lines()):
                    text, done, usage_total = state.apply(event)
                    if text:
                        yield _chat_sse_line(model.id, text)
                    if done:
                        usage = {"prompt_tokens": 0, "completion_tokens": usage_total, "total_tokens": usage_total}
                        yield _chat_sse_line(model.id, "", "stop", usage)
                        yield b"data: [DONE]\n\n"
                        break
            finally:
                upstream.close()
                client.close()
                _delete_session(model.base_url, token, session_id)
        return 200, chunks()

    state = _PatchState()
    text_parts: list[str] = []
    try:
        for event in _iter_data_events(upstream.iter_lines()):
            text, done, _usage_total = state.apply(event)
            if text:
                text_parts.append(text)
            if done:
                break
    finally:
        upstream.close()
        client.close()
        _delete_session(model.base_url, token, session_id)
    return 200, _chat_completion_body(model.id, "".join(text_parts), state.usage)
