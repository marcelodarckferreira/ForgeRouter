"""In-process, advisory rate-limit ledger: tracks a rolling per-minute request
count per (provider, model_id) and learns a conservative ceiling from observed
429s, so a model about to hit its own free-tier cap sorts after ones that
aren't — the same deprioritize-never-exclude treatment as the circuit breaker
in app/routing_state.py, but proactive: it tries to avoid the 429 instead of
only recovering from one already hit. Advisory and in-memory: resets on
restart, never removes the last resort.
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque

_lock = threading.Lock()

_MAX_TIMESTAMPS_PER_KEY = 1000

_requests: dict[tuple[str, str], deque[float]] = {}
_ceilings: dict[tuple[str, str], tuple[int, float]] = {}  # (provider, model_id) -> (ceiling, learned_at)


def _window_seconds() -> float:
    return float(os.environ.get("RATE_LEDGER_WINDOW_SECONDS", "60"))


def _ceiling_ttl_seconds() -> float:
    # How long a learned ceiling is trusted before being forgotten — a provider
    # that stops rate-limiting a model should eventually regain full priority
    # instead of being deprioritized forever off one old burst.
    return float(os.environ.get("RATE_LEDGER_CEILING_TTL_SECONDS", "900"))


def _prune(timestamps: deque[float], now: float) -> None:
    window = _window_seconds()
    while timestamps and now - timestamps[0] > window:
        timestamps.popleft()


def record_attempt(provider: str, model_id: str) -> None:
    now = time.monotonic()
    key = (provider, model_id)
    with _lock:
        timestamps = _requests.setdefault(key, deque())
        timestamps.append(now)
        _prune(timestamps, now)
        while len(timestamps) > _MAX_TIMESTAMPS_PER_KEY:
            timestamps.popleft()


def record_rate_limit_hit(provider: str, model_id: str) -> None:
    # Learn the tightest ceiling ever observed (never raise it back up on a
    # looser 429 — being conservative about a free-tier cap is the safe
    # direction to be wrong in) and refresh its TTL either way.
    now = time.monotonic()
    key = (provider, model_id)
    with _lock:
        timestamps = _requests.get(key)
        count = len(timestamps) if timestamps else 1
        existing = _ceilings.get(key)
        ceiling = min(existing[0], count) if existing else max(1, count)
        _ceilings[key] = (max(1, ceiling), now)


def near_ceiling(provider: str, model_id: str) -> bool:
    now = time.monotonic()
    key = (provider, model_id)
    with _lock:
        entry = _ceilings.get(key)
        if entry is None:
            return False
        ceiling, learned_at = entry
        if now - learned_at > _ceiling_ttl_seconds():
            _ceilings.pop(key, None)
            return False
        timestamps = _requests.get(key)
        if not timestamps:
            return False
        _prune(timestamps, now)
        return len(timestamps) >= ceiling


def reset() -> None:
    """Test-only: clear all state between tests (mirrors routing_state.reset)."""
    with _lock:
        _requests.clear()
        _ceilings.clear()
