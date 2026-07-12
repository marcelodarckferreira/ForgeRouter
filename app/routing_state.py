"""In-process routing state: provider circuit breaker, sticky routing
(last-known-good model per agent+demand) and a cached model-performance map.

All of it is advisory and in-memory: it reorders or deprioritizes candidates,
never removes the last resort, and resets on restart. Nothing here may touch
the DB in a way that breaks routing — the performance loader fails open.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

_lock = threading.Lock()

# Circuit breaker: consecutive failures per provider. At threshold the provider
# "opens" and its models sort last for a cooldown; after the cooldown one probe
# is allowed (half-open) and a single failure re-opens it immediately.
_breaker_failures: dict[str, int] = {}
_breaker_opened_at: dict[str, float] = {}

# Sticky routing: last successful model per (agent, demand). Keeping a
# conversation on the same model preserves the provider's prompt cache.
_sticky: dict[tuple[str, str], tuple[str, float]] = {}

# model_performance() cache: one DB aggregate per TTL, shared by all requests.
_perf_cache: dict[str, Any] = {"at": 0.0, "data": {}}
_PERF_TTL_SECONDS = 60.0


def _breaker_threshold() -> int:
    return int(os.environ.get("BREAKER_THRESHOLD", "4"))


def _breaker_cooldown() -> float:
    return float(os.environ.get("BREAKER_COOLDOWN_SECONDS", "120"))


def _sticky_ttl() -> float:
    return float(os.environ.get("STICKY_TTL_SECONDS", "600"))


def record_provider_failure(provider: str) -> None:
    with _lock:
        count = _breaker_failures.get(provider, 0) + 1
        _breaker_failures[provider] = count
        if count >= _breaker_threshold():
            _breaker_opened_at[provider] = time.monotonic()


def record_provider_success(provider: str) -> None:
    with _lock:
        _breaker_failures.pop(provider, None)
        _breaker_opened_at.pop(provider, None)


def breaker_open(provider: str) -> bool:
    with _lock:
        opened_at = _breaker_opened_at.get(provider)
        if opened_at is None:
            return False
        if time.monotonic() - opened_at >= _breaker_cooldown():
            # Half-open: allow a probe; the next failure re-opens immediately.
            _breaker_opened_at.pop(provider, None)
            _breaker_failures[provider] = _breaker_threshold() - 1
            return False
        return True


def record_sticky(agent: str | None, demand: str | None, model_id: str) -> None:
    if not demand:
        return
    with _lock:
        _sticky[(agent or "", demand)] = (model_id, time.monotonic())


def sticky_model(agent: str | None, demand: str | None) -> str | None:
    if not demand:
        return None
    ttl = _sticky_ttl()
    if ttl <= 0:
        return None
    with _lock:
        entry = _sticky.get((agent or "", demand))
        if entry is None:
            return None
        model_id, recorded_at = entry
        if time.monotonic() - recorded_at >= ttl:
            _sticky.pop((agent or "", demand), None)
            return None
        return model_id


def model_performance_cached() -> dict[str, dict[str, Any]]:
    """Recent per-model stats for dynamic_score. A failing/unreachable DB
    yields an empty map (static scores apply) and is retried after the TTL."""
    now = time.monotonic()
    with _lock:
        if now - _perf_cache["at"] < _PERF_TTL_SECONDS:
            return _perf_cache["data"]
    try:
        from app.storage import model_performance

        data = model_performance()
    except Exception:
        data = {}
    with _lock:
        _perf_cache["at"] = now
        _perf_cache["data"] = data
    return data


def reset() -> None:
    """Test hook: clear breaker, sticky and performance-cache state."""
    with _lock:
        _breaker_failures.clear()
        _breaker_opened_at.clear()
        _sticky.clear()
        _perf_cache["at"] = 0.0
        _perf_cache["data"] = {}
