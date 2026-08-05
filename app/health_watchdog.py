from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class _WatchdogState:
    healthy_enabled: int | None = None
    total_enabled: int | None = None
    min_healthy: int | None = None
    cooldown_seconds: int | None = None
    degraded: bool = False
    last_check_at: datetime | None = None
    last_scan_at: datetime | None = None


_state = _WatchdogState()


def reset() -> None:
    global _state
    _state = _WatchdogState()


def snapshot() -> dict[str, Any]:
    return {
        "healthy_enabled": _state.healthy_enabled,
        "total_enabled": _state.total_enabled,
        "min_healthy": _state.min_healthy,
        "cooldown_seconds": _state.cooldown_seconds,
        "degraded": _state.degraded,
        "last_check_at": _state.last_check_at.isoformat() if _state.last_check_at else None,
        "last_scan_at": _state.last_scan_at.isoformat() if _state.last_scan_at else None,
    }


def note_check(healthy_enabled: int, total_enabled: int, min_healthy: int, cooldown_seconds: int, now: datetime) -> None:
    _state.healthy_enabled = healthy_enabled
    _state.total_enabled = total_enabled
    _state.min_healthy = min_healthy
    _state.cooldown_seconds = cooldown_seconds
    _state.degraded = healthy_enabled < min_healthy
    _state.last_check_at = now


def should_rescan(now: datetime, cooldown_seconds: int) -> bool:
    # Loop guard: even if the pool is still below the minimum on every tick, only
    # one real (network-hitting) rescan may run per cooldown window.
    if _state.last_scan_at is None:
        return True
    return (now - _state.last_scan_at).total_seconds() >= cooldown_seconds


def note_scan(now: datetime) -> None:
    _state.last_scan_at = now
