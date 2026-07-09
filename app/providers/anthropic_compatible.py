"""Generic Anthropic Messages API provider client.

Providers registered with api_format = "anthropic" expose Anthropic's
/v1/messages wire protocol instead of OpenAI /chat/completions — the Anthropic
API with a regular key, or any Anthropic-compatible proxy. The payload/stream
translation is shared with the Claude Code adapter, minus the OAuth
particularities (no system-prompt prefix, no beta header; auth is the
provider's stored/env API key sent as x-api-key and Bearer, covering both the
Anthropic spec and Bearer-only proxies). ForgeRouter itself keeps speaking
chat completions internally, so the router, scanner and usage accounting need
no special cases.
"""

from __future__ import annotations

import os
from typing import Any, Iterator

import httpx

from app.providers.claude_code import (
    build_messages_request,
    fold_message_to_completion,
    iter_sse_events,
    stream_events_as_chunks,
)
from app.registry import ProviderModel


def anthropic_messages_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/messages"):
        return base
    if base.endswith("/v1"):
        return base + "/messages"
    return base + "/v1/messages"


def anthropic_headers(model: ProviderModel) -> dict[str, str]:
    api_key = model.api_key or (os.environ.get(model.api_key_env, "") if model.api_key_env else "")
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key
        headers["Authorization"] = f"Bearer {api_key}"
    headers.update(getattr(model, "extra_headers", None) or {})
    return headers


def anthropic_chat_completion(model: ProviderModel, chat_payload: dict[str, Any], timeout: float = 120.0) -> tuple[int, Any]:
    """Adapter entry point, mirroring openai_compatible.chat_completion's contract:
    (status, dict) for non-stream calls, (status, bytes-iterator) for stream."""
    url = anthropic_messages_url(model.base_url)
    request_body = build_messages_request(chat_payload, model.provider_model, system_prefix=None)

    client = httpx.Client(timeout=timeout)
    try:
        request = client.build_request("POST", url, headers=anthropic_headers(model), json=request_body)
        response = client.send(request, stream=True)
    except Exception:
        client.close()
        raise

    if response.status_code >= 400:
        try:
            response.read()
            body = response.json()
        except Exception:
            body = {"error": {"message": (response.text or f"http_{response.status_code}")[:500], "type": "anthropic_http_error"}}
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
