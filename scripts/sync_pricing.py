#!/usr/bin/env python
"""Full reference-cost pricing sync: catalog + live provider prices + backfill.

Same three steps as POST /admin/pricing/sync, runnable from the CLI/cron so
pricing data doesn't only update when someone happens to click Sync in the
dashboard — mirrors the health scanner's cron pattern (see CLAUDE.md).

    docker run --rm --network host --env-file .env -e PYTHONPATH=/app \
        forgerouter:latest python3 scripts/sync_pricing.py

Suggested host crontab (weekly, prices don't move fast enough to need more):
    0 6 * * 1 cd /path/to/forgerouter && docker run --rm --network host \
        --env-file .env -e PYTHONPATH=/app forgerouter:latest \
        python3 scripts/sync_pricing.py >> /var/log/forgerouter-pricing-sync.log 2>&1
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.pricing import sync_catalog_from_litellm, sync_provider_pricing
from app.registry import load_registry_with_db_health
from app.storage import backfill_reference_costs, set_setting


def main() -> None:
    catalog_entries = sync_catalog_from_litellm()
    print(f"LiteLLM catalog: {catalog_entries} entries")

    registry = load_registry_with_db_health()
    live_entries = sync_provider_pricing(registry)
    print(f"Live provider pricing: {live_entries} entries")

    checked, priced = backfill_reference_costs()
    print(f"Backfill: {priced}/{checked} historical messages priced")

    set_setting("pricing_last_synced", datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    main()
