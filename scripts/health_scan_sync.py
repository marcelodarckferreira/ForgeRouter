#!/usr/bin/env python
"""Rotating-batch provider health scan: scans a percentage of the model pool per
run instead of every model every time, so a frequent cron cadence stays cheap on
free-tier quotas (each scanned model burns one real chat completion). A cursor
persisted in ai_router.settings advances every run, so consecutive runs walk the
full pool in a ring — a model that was skipped this run gets caught next run,
usually within a couple of cycles.

Full parity with the dashboard's Routing page "Refresh" button
(POST /admin/providers/rescan), just scoped to the current batch: scans, persists
health, mirrors the verdict into each model's on/off selection (manual_off is
never overridden), and reconciles every agent's model list.

Small pools (e.g. only 2 eligible models) never loop or stall: batch_size is
clamped to min(total, ...), so a run just scans the whole (tiny) pool every
time — no special-casing needed, no run ever waits on another or grows without
bound. Each run does a fixed amount of work (one bounded ThreadPoolExecutor
batch, one settings write) and exits; nothing here is recursive or polls itself.

    docker run --rm --network foundation_network --add-host=host.docker.internal:host-gateway \
        --env-file .env -e PYTHONPATH=/app forgerouter:latest \
        python3 scripts/health_scan_sync.py --percent 20

Suggested host crontab (every 10 minutes, ~20%/run — full pool covered roughly
every 50 minutes; flock -n makes an overrunning scan skip the next tick instead
of piling up — self-preservation: no overlapping runs, no container pile-up,
each container is --rm so a crashed run leaves nothing behind):
    */10 * * * * flock -n /tmp/forgerouter-health-scan.lock \
        docker run --rm --network foundation_network --add-host=host.docker.internal:host-gateway \
        --env-file /root/project/forgerouter/.env -e PYTHONPATH=/app forgerouter:latest \
        python3 scripts/health_scan_sync.py --percent 20 \
        >> /var/log/forgerouter-health-scan.log 2>&1

Tune --percent against the size of the model pool and how fast free-tier quotas
reset: a bigger pool or tighter quotas want a lower percentage (or a longer cron
interval) so the ring doesn't burn through a model's daily quota just scanning it.
"""

from __future__ import annotations

import argparse
import math
from concurrent.futures import ThreadPoolExecutor

from app.registry import load_provider_dicts, registry_from_provider_dicts
from app.storage import (
    get_setting,
    persist_health_results,
    set_models_enabled_from_health,
    set_setting,
    sync_agent_model_associations,
)
from app.validation.scanner import build_scan_payload, scan_model

CURSOR_KEY = "health_scan_cursor"


def eligible_models():
    registry = registry_from_provider_dicts(load_provider_dicts())
    # Same filter as scan_registry(): manually-disabled models are skipped
    # (deliberate curation — scanning them wastes free-tier rate limits).
    models = [m for m in registry.models if m.enabled or not m.manual_off]
    models.sort(key=lambda m: m.id)  # deterministic order so the cursor is stable across runs
    return models


def next_batch(models: list, percent: float, min_batch: int) -> tuple[list, int]:
    total = len(models)
    if total == 0:
        return [], 0
    batch_size = min(total, max(min_batch, math.ceil(total * percent / 100)))
    cursor = int(get_setting(CURSOR_KEY, "0") or "0") % total
    end = cursor + batch_size
    batch = models[cursor:end] if end <= total else models[cursor:] + models[: end - total]
    return batch, end % total


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotating-batch ForgeRouter provider health scan")
    parser.add_argument("--percent", type=float, default=20.0, help="Percent of the eligible model pool to scan this run (default: 20)")
    parser.add_argument("--min-batch", type=int, default=5, help="Minimum models scanned per run regardless of percent (default: 5)")
    args = parser.parse_args()

    models = eligible_models()
    batch, next_cursor = next_batch(models, args.percent, args.min_batch)
    if not batch:
        print("No eligible models to scan.")
        return 0

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda model: scan_model(model, timeout=30.0), batch))

    persist_health_results(results)
    changed = set_models_enabled_from_health(results)
    sync_result = sync_agent_model_associations()
    set_setting(CURSOR_KEY, str(next_cursor))

    payload = build_scan_payload(results)
    print(
        f"Scanned {len(batch)}/{len(models)} models "
        f"({payload['summary']['healthy']} healthy, {payload['summary']['unhealthy']} unhealthy) — "
        f"cursor {next_cursor}/{len(models)}"
    )
    print(f"Enabled-flag changes: {changed}; agent associations added={sync_result['associations_added']} removed={sync_result['associations_removed']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
