from datetime import datetime, timedelta, timezone

import pytest

from app import health_watchdog


@pytest.fixture(autouse=True)
def _reset_watchdog_state():
    health_watchdog.reset()
    yield
    health_watchdog.reset()


def test_initial_snapshot_is_empty():
    snap = health_watchdog.snapshot()
    assert snap == {
        "healthy_enabled": None,
        "total_enabled": None,
        "min_healthy": None,
        "cooldown_seconds": None,
        "degraded": False,
        "last_check_at": None,
        "last_scan_at": None,
    }


def test_note_check_marks_degraded_below_minimum():
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    health_watchdog.note_check(healthy_enabled=1, total_enabled=10, min_healthy=3, cooldown_seconds=300, now=now)
    snap = health_watchdog.snapshot()
    assert snap["degraded"] is True
    assert snap["healthy_enabled"] == 1
    assert snap["total_enabled"] == 10
    assert snap["min_healthy"] == 3
    assert snap["cooldown_seconds"] == 300
    assert snap["last_check_at"] == now.isoformat()


def test_note_check_not_degraded_at_or_above_minimum():
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    health_watchdog.note_check(healthy_enabled=3, total_enabled=10, min_healthy=3, cooldown_seconds=300, now=now)
    assert health_watchdog.snapshot()["degraded"] is False


def test_should_rescan_true_when_never_scanned():
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    assert health_watchdog.should_rescan(now, cooldown_seconds=300) is True


def test_should_rescan_false_within_cooldown():
    scanned_at = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    health_watchdog.note_scan(scanned_at)

    still_cooling = scanned_at + timedelta(seconds=299)
    assert health_watchdog.should_rescan(still_cooling, cooldown_seconds=300) is False


def test_should_rescan_true_once_cooldown_elapses():
    scanned_at = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    health_watchdog.note_scan(scanned_at)

    after_cooldown = scanned_at + timedelta(seconds=300)
    assert health_watchdog.should_rescan(after_cooldown, cooldown_seconds=300) is True


def test_note_scan_updates_last_scan_at():
    assert health_watchdog.snapshot()["last_scan_at"] is None
    scanned_at = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    health_watchdog.note_scan(scanned_at)
    assert health_watchdog.snapshot()["last_scan_at"] == scanned_at.isoformat()


def test_reset_clears_all_state():
    now = datetime(2026, 8, 5, 12, 0, 0, tzinfo=timezone.utc)
    health_watchdog.note_check(healthy_enabled=0, total_enabled=5, min_healthy=3, cooldown_seconds=300, now=now)
    health_watchdog.note_scan(now)
    assert health_watchdog.snapshot()["degraded"] is True

    health_watchdog.reset()

    assert health_watchdog.snapshot() == {
        "healthy_enabled": None,
        "total_enabled": None,
        "min_healthy": None,
        "cooldown_seconds": None,
        "degraded": False,
        "last_check_at": None,
        "last_scan_at": None,
    }
