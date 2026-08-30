"""Google Antigravity (Gemini Code Assist) coding plan protocol adapter.

The Antigravity backend (cloudcode-pa.googleapis.com/v1internal) is not
OpenAI-compatible: it speaks Google's internal Cloud Code Assist API
(generateContent / streamGenerateContent), ties usage to a
`cloudaicompanionProject` resolved via a loadCodeAssist handshake, and
authenticates with the OAuth access token from the Antigravity CLI login
(~/.gemini/antigravity-cli/antigravity-oauth-token -> token.access_token).
This module translates chat-completions requests into Gemini generateContent
payloads and folds (or re-streams) the response back as chat completions, so
the rest of ForgeRouter treats Antigravity like any other provider. As with
Codex, ForgeRouter does not refresh the OAuth token itself — it relies on the
`agy` CLI being run periodically on the host to keep the token file fresh.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import uuid
from typing import Any, Iterable, Iterator

import httpx

from app.registry import ProviderModel

ANTIGRAVITY_BASE_MARKER = "cloudcode-pa.googleapis.com"

# Static fallback model catalog — models supported by the Antigravity (agy) CLI.
# The health scan decides which ones actually work for the account.
ANTIGRAVITY_MODELS: list[dict[str, Any]] = [
    {"id": "gemini-3.7-flash-high", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.7-flash-medium", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.7-flash-low", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.6-flash-high", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.6-flash-medium", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.6-flash-low", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.5-flash-high", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.5-flash-medium", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.5-flash-low", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.1-pro-high", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.1-pro-low", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-2.5-pro", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-2.5-flash", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-2.5-flash-lite", "capabilities": ["text", "code", "tool_call", "vision"]},
    {"id": "gemini-3-pro-preview", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3-flash-preview", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gemini-3.1-flash-lite-preview", "capabilities": ["text", "code", "tool_call", "vision"]},
    {"id": "claude-sonnet-4-6", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "claude-opus-4-6-thinking", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
    {"id": "gpt-oss-120b-medium", "capabilities": ["text", "code", "reasoning", "tool_call", "vision"]},
]


def is_antigravity_base_url(base_url: str | None) -> bool:
    return ANTIGRAVITY_BASE_MARKER in (base_url or "")


ANTIGRAVITY_AUTH_FILE = os.environ.get(
    "ANTIGRAVITY_AUTH_FILE", os.path.expanduser("~/.gemini/antigravity-cli/antigravity-oauth-token")
)

ANTIGRAVITY_CLIENT_METADATA = {
    "ideType": "IDE_UNSPECIFIED",
    "platform": "PLATFORM_UNSPECIFIED",
    "pluginType": "GEMINI",
    "duetProject": "",
}

# cloudaicompanionProject is stable for an account — cache it in-memory to avoid
# a loadCodeAssist round-trip on every chat completion.
_project_cache: dict[str, Any] = {"id": "", "checked_at": 0.0}
_PROJECT_CACHE_TTL_SECONDS = 3600.0

FINISH_REASON_MAP = {
    "STOP": "stop",
    "MAX_TOKENS": "length",
    "SAFETY": "content_filter",
    "RECITATION": "content_filter",
}


def _auth_file_token() -> str:
    try:
        with open(ANTIGRAVITY_AUTH_FILE, encoding="utf-8") as fh:
            return str((json.load(fh).get("token") or {}).get("access_token") or "")
    except Exception:
        return ""


def _find_agy_bin() -> str:
    path_override = os.environ.get("AGY_CLI_PATH")
    if path_override and os.path.exists(path_override):
        return path_override
    for candidate in [
        shutil.which("agy"),
        "/usr/local/bin/agy",
        os.path.expanduser("~/.local/bin/agy"),
        "/root/.local/bin/agy",
    ]:
        if candidate and os.path.exists(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return ""


def antigravity_discover_models() -> list[dict[str, Any]]:
    agy_bin = _find_agy_bin()
    if agy_bin:
        try:
            res = subprocess.run([agy_bin, "models"], capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                discovered = []
                for line in res.stdout.splitlines():
                    line = line.strip()
                    if line and not line.startswith("⠋") and not line.startswith("Fetching") and not line.startswith("⠙") and not line.startswith("⠹") and not line.startswith("⠸") and not line.startswith("⠼") and not line.startswith("⠴") and not line.startswith("⠦") and not line.startswith("⠧") and not line.startswith("⠇") and not line.startswith("⠏"):
                        parts = line.split()
                        if parts:
                            m_id = parts[0]
                            discovered.append({
                                "id": m_id,
                                "capabilities": ["text", "code", "reasoning", "tool_call", "vision"],
                            })
                if discovered:
                    return discovered
        except Exception:
            pass
    return [dict(model) for model in ANTIGRAVITY_MODELS]


def antigravity_token(api_key: str = "", api_key_env: str = "") -> str:
    """Antigravity credential resolution: stored key -> env var -> the Antigravity
    CLI login (~/.gemini/antigravity-cli/antigravity-oauth-token). With `agy`
    logged in on this machine nothing needs to be stored, and the token stays
    fresh as the CLI refreshes it on use."""
    if api_key:
        return api_key
    if api_key_env and os.environ.get(api_key_env):
        return os.environ[api_key_env]
    return _auth_file_token()


def resolve_cloud_project(base_url: str, token: str, timeout: float = 30.0) -> str:
    """The Code Assist API ties usage to a cloudaicompanionProject resolved via
    loadCodeAssist; cache it since it is stable for the account."""
    now = time.time()
    if _project_cache["id"] and now - _project_cache["checked_at"] < _PROJECT_CACHE_TTL_SECONDS:
        return str(_project_cache["id"])
    try:
        response = httpx.post(
            base_url.rstrip("/") + ":loadCodeAssist",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"metadata": ANTIGRAVITY_CLIENT_METADATA},
            timeout=timeout,
        )
        response.raise_for_status()
        project = str(response.json().get("cloudaicompanionProject") or "")
    except Exception:
        project = ""
    if project:
        _project_cache.update(id=project, checked_at=now)
    return project


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


def _inline_image(url: str) -> dict[str, Any] | None:
    if url.startswith("data:"):
        try:
            header, data = url.split(",", 1)
            mime = header[len("data:"):].split(";")[0] or "image/png"
            return {"inlineData": {"mimeType": mime, "data": data}}
        except Exception:
            return None
    if url.startswith("http://") or url.startswith("https://"):
        try:
            response = httpx.get(url, timeout=20.0)
            mime = response.headers.get("content-type", "image/png").split(";")[0]
            return {"inlineData": {"mimeType": mime, "data": base64.b64encode(response.content).decode()}}
        except Exception:
            return None
    return None


def _gemini_parts(content: Any) -> list[dict[str, Any]]:
    if isinstance(content, str) or content is None:
        return [{"text": content or ""}]
    parts: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "text":
            parts.append({"text": part.get("text", "")})
        elif part.get("type") == "image_url":
            image = _inline_image((part.get("image_url") or {}).get("url", ""))
            if image:
                parts.append(image)
    return parts or [{"text": ""}]


def build_generate_content_request(chat_payload: dict[str, Any], project: str, model_id: str) -> dict[str, Any]:
    """chat-completions request -> Code Assist generateContent request."""
    system_parts: list[dict[str, Any]] = []
    contents: list[dict[str, Any]] = []
    for message in chat_payload.get("messages", []):
        role = message.get("role", "user")
        if role == "system":
            text = _text_of(message.get("content"))
            if text:
                system_parts.append({"text": text})
            continue
        if role == "tool":
            contents.append(
                {
                    "role": "function",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": message.get("name") or "tool",
                                "response": {"result": _text_of(message.get("content"))},
                            }
                        }
                    ],
                }
            )
            continue
        if role == "assistant" and message.get("tool_calls"):
            parts: list[dict[str, Any]] = []
            text = _text_of(message.get("content"))
            if text:
                parts.append({"text": text})
            for call in message["tool_calls"]:
                function = (call or {}).get("function") or {}
                try:
                    args = json.loads(function.get("arguments") or "{}")
                except Exception:
                    args = {}
                parts.append({"functionCall": {"name": function.get("name") or "", "args": args}})
            contents.append({"role": "model", "parts": parts})
            continue
        contents.append({"role": "model" if role == "assistant" else "user", "parts": _gemini_parts(message.get("content"))})

    request: dict[str, Any] = {"contents": contents}
    if system_parts:
        request["systemInstruction"] = {"parts": system_parts}

    generation_config: dict[str, Any] = {}
    if chat_payload.get("temperature") is not None:
        generation_config["temperature"] = chat_payload["temperature"]
    if chat_payload.get("max_tokens") is not None:
        generation_config["maxOutputTokens"] = chat_payload["max_tokens"]
    if generation_config:
        request["generationConfig"] = generation_config

    tools = [
        {
            "name": (tool.get("function") or {}).get("name") or "",
            "description": (tool.get("function") or {}).get("description") or "",
            "parameters": (tool.get("function") or {}).get("parameters") or {"type": "object", "properties": {}},
        }
        for tool in chat_payload.get("tools") or []
        if isinstance(tool, dict) and tool.get("type") == "function"
    ]
    if tools:
        request["tools"] = [{"functionDeclarations": tools}]

    payload: dict[str, Any] = {"model": model_id, "request": request}
    if project:
        payload["project"] = project
    return payload


def _usage_from_metadata(usage_metadata: dict[str, Any]) -> dict[str, int]:
    return {
        "prompt_tokens": int(usage_metadata.get("promptTokenCount") or 0),
        "completion_tokens": int(usage_metadata.get("candidatesTokenCount") or 0),
        "total_tokens": int(usage_metadata.get("totalTokenCount") or 0),
    }


def _parts_to_message(parts: Iterable[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    text_chunks: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    for part in parts:
        if not isinstance(part, dict) or part.get("thought"):
            continue
        if "functionCall" in part:
            call = part["functionCall"]
            tool_calls.append(
                {
                    "id": f"call_{uuid.uuid4().hex[:24]}",
                    "type": "function",
                    "function": {"name": call.get("name") or "", "arguments": json.dumps(call.get("args") or {})},
                }
            )
        elif "text" in part:
            text_chunks.append(part["text"])
    message: dict[str, Any] = {"role": "assistant", "content": "".join(text_chunks) or None}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message, tool_calls


def fold_response_to_completion(body: dict[str, Any], model_id: str) -> tuple[int, dict[str, Any]]:
    """generateContent response -> chat.completion."""
    response = body.get("response") or {}
    candidates = response.get("candidates") or []
    if not candidates:
        error = body.get("error") or {}
        return 502, {"error": {"message": error.get("message") or "antigravity_empty_response", "type": "antigravity_response_failed"}}
    candidate = candidates[0]
    parts = (candidate.get("content") or {}).get("parts") or []
    message, tool_calls = _parts_to_message(parts)
    finish = FINISH_REASON_MAP.get(candidate.get("finishReason") or "STOP", "stop")
    if tool_calls:
        finish = "tool_calls"
    return 200, {
        "id": f"antigravity-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": _usage_from_metadata(response.get("usageMetadata") or {}),
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
    """Re-emit a streamGenerateContent SSE stream as chat.completion.chunk SSE,
    ending with a usage chunk (picked up by the router's usage accounting) and
    [DONE]."""
    completion_id = f"antigravity-{uuid.uuid4()}"
    started = False
    tool_call_count = 0
    finish = "stop"
    usage: dict[str, int] | None = None
    for event in events:
        response = event.get("response") or {}
        candidates = response.get("candidates") or []
        if not candidates:
            error = event.get("error") or {}
            if error:
                yield _chunk(model_id, completion_id, {"content": f"\n[antigravity error: {error.get('message') or 'response failed'}]"})
            continue
        candidate = candidates[0]
        usage_metadata = response.get("usageMetadata")
        if usage_metadata:
            usage = _usage_from_metadata(usage_metadata)
        for part in (candidate.get("content") or {}).get("parts") or []:
            if not isinstance(part, dict) or part.get("thought"):
                continue
            if "functionCall" in part:
                call = part["functionCall"]
                delta: dict[str, Any] = {
                    "tool_calls": [
                        {
                            "index": tool_call_count,
                            "id": f"call_{uuid.uuid4().hex[:24]}",
                            "type": "function",
                            "function": {"name": call.get("name") or "", "arguments": json.dumps(call.get("args") or {})},
                        }
                    ]
                }
                if not started:
                    delta["role"] = "assistant"
                    started = True
                tool_call_count += 1
                finish = "tool_calls"
                yield _chunk(model_id, completion_id, delta)
            elif "text" in part and part["text"]:
                delta = {"content": part["text"]}
                if not started:
                    delta["role"] = "assistant"
                    started = True
                yield _chunk(model_id, completion_id, delta)
        if candidate.get("finishReason") and finish == "stop":
            finish = FINISH_REASON_MAP.get(candidate["finishReason"], "stop")
    yield _chunk(model_id, completion_id, {}, finish=finish, usage=usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})
    yield b"data: [DONE]\n\n"


def _format_messages_for_cli(messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for msg in messages:
        role = msg.get("role", "user")
        content = _text_of(msg.get("content"))
        if role == "system":
            parts.append(f"Instructions:\n{content}")
        elif role == "user":
            parts.append(f"User:\n{content}")
        elif role == "assistant":
            parts.append(f"Assistant:\n{content}")
        else:
            parts.append(f"{role}:\n{content}")
    return "\n\n".join(parts) if parts else "Hello"


def _stream_agy_chunks(proc: subprocess.Popen, model_id: str) -> Iterator[bytes]:
    completion_id = f"antigravity-{uuid.uuid4()}"
    started = False
    usage: dict[str, int] | None = None
    try:
        if proc.stdout:
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except Exception:
                    continue
                evt_type = event.get("event")
                if evt_type == "step_update":
                    step = event.get("step_update") or {}
                    delta_text = step.get("text_delta")
                    if delta_text:
                        delta: dict[str, Any] = {"content": delta_text}
                        if not started:
                            delta["role"] = "assistant"
                            started = True
                        chunk = {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model_id,
                            "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n".encode()
                    if step.get("usage"):
                        u = step["usage"]
                        usage = {
                            "prompt_tokens": int(u.get("input_tokens") or 0),
                            "completion_tokens": int(u.get("output_tokens") or 0),
                            "total_tokens": int(u.get("total_tokens") or 0),
                        }
                elif evt_type == "result":
                    res = event.get("result") or {}
                    if res.get("usage"):
                        u = res["usage"]
                        usage = {
                            "prompt_tokens": int(u.get("input_tokens") or 0),
                            "completion_tokens": int(u.get("output_tokens") or 0),
                            "total_tokens": int(u.get("total_tokens") or 0),
                        }
    finally:
        try:
            proc.kill()
        except Exception:
            pass
    final_chunk = {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model_id,
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
    yield f"data: {json.dumps(final_chunk)}\n\n".encode()
    yield b"data: [DONE]\n\n"


def _agy_chat_completion(agy_bin: str, model: ProviderModel, chat_payload: dict[str, Any], timeout: float = 120.0) -> tuple[int, Any]:
    prompt = _format_messages_for_cli(chat_payload.get("messages", []))
    model_name = model.provider_model or model.id.split("/")[-1]
    stream = bool(chat_payload.get("stream"))
    cmd = [
        agy_bin,
        "--print",
        prompt,
        "--model",
        model_name,
        "--disable-slash-commands",
        "--dangerously-skip-permissions",
        "--output-format",
        "stream-json" if stream else "json",
    ]
    if stream:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            return 200, _stream_agy_chunks(proc, model.id)
        except Exception as exc:
            return 502, {"error": {"message": f"failed to launch agy: {exc}", "type": "antigravity_exec_error"}}

    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as exc:
        return 502, {"error": {"message": f"agy execution error: {exc}", "type": "antigravity_exec_error"}}

    if res.returncode != 0:
        return 502, {"error": {"message": res.stderr.strip() or f"agy exited with code {res.returncode}", "type": "antigravity_exec_error"}}

    try:
        data = json.loads(res.stdout)
    except Exception:
        return 502, {"error": {"message": f"invalid json response from agy: {res.stdout[:300]}", "type": "antigravity_parse_error"}}

    text = data.get("response", "")
    usage_info = data.get("usage") or {}
    usage = {
        "prompt_tokens": int(usage_info.get("input_tokens") or 0),
        "completion_tokens": int(usage_info.get("output_tokens") or 0),
        "total_tokens": int(usage_info.get("total_tokens") or 0),
    }
    completion_id = f"antigravity-{uuid.uuid4()}"
    return 200, {
        "id": completion_id,
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model.id,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": usage,
    }


def antigravity_chat_completion(model: ProviderModel, chat_payload: dict[str, Any], timeout: float = 120.0) -> tuple[int, Any]:
    """Adapter entry point, mirroring openai_compatible.chat_completion's contract:
    (status, dict) for non-stream calls, (status, bytes-iterator) for stream."""
    agy_bin = _find_agy_bin()
    if agy_bin:
        return _agy_chat_completion(agy_bin, model, chat_payload, timeout=timeout)

    token = antigravity_token(model.api_key or "", model.api_key_env or "")
    if not token:
        return 401, {
            "error": {
                "message": "Antigravity CLI not logged in on this server (~/.gemini/antigravity-cli/antigravity-oauth-token missing)",
                "type": "antigravity_auth_error",
            }
        }

    base = model.base_url.rstrip("/")
    project = resolve_cloud_project(base, token, timeout=min(timeout, 30.0))
    request_body = build_generate_content_request(chat_payload, project, model.provider_model)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    headers.update(getattr(model, "extra_headers", None) or {})

    stream = bool(chat_payload.get("stream"))
    url = base + (":streamGenerateContent?alt=sse" if stream else ":generateContent")

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
            body = {"error": {"message": (response.text or f"http_{response.status_code}")[:500], "type": "antigravity_http_error"}}
        response.close()
        client.close()
        return response.status_code, body

    if stream:
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
    return fold_response_to_completion(body, model.id)
