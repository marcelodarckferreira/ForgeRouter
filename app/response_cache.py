"""Opt-in, in-process exact-match response cache for non-streaming chat
completions. Off by default (ai_router.settings response_cache_enabled) and
overridable per request via the X-Proxyrouter-Cache: on|off header (same
internal x-proxyrouter- prefix as x-proxyrouter-request-id/-model).

Advisory and in-memory like app/routing_state.py: bounded LRU, resets on
restart, and a cache miss (including any lookup error) must always fall
through to the normal routing path — a broken cache may never break routing.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from typing import Any

_lock = threading.Lock()
_MAX_ENTRIES = 500

# key -> (stored_at monotonic seconds, response body). Ordered so eviction
# drops the least-recently-used entry once the cache is full.
_entries: "OrderedDict[str, tuple[float, dict[str, Any]]]" = OrderedDict()


def cache_key(
    agent_name: str | None,
    model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    temperature: float | None,
    max_tokens: int | None,
) -> str:
    # Keyed on the caller's own request shape, not on anything ForgeRouter
    # derives internally (selected candidate, truncation, normalization) —
    # those can vary run to run with provider health, which would silently
    # fragment or misfire an "exact match" cache keyed on derived state.
    canonical = json.dumps(
        {
            "agent": agent_name,
            "model": model,
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def get(key: str, ttl_seconds: int) -> dict[str, Any] | None:
    with _lock:
        entry = _entries.get(key)
        if entry is None:
            return None
        stored_at, body = entry
        if time.monotonic() - stored_at > ttl_seconds:
            _entries.pop(key, None)
            return None
        _entries.move_to_end(key)
        return body


def put(key: str, body: dict[str, Any]) -> None:
    with _lock:
        _entries[key] = (time.monotonic(), body)
        _entries.move_to_end(key)
        while len(_entries) > _MAX_ENTRIES:
            _entries.popitem(last=False)


def reset() -> None:
    """Test-only: clear all entries between tests (mirrors routing_state.reset)."""
    with _lock:
        _entries.clear()
