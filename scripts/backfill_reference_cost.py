#!/usr/bin/env python
"""One-off backfill: compute reference_cost for existing route_events rows.

persist_route_event only computes reference_cost for NEW rows (see
app/storage.py). Rows written before that feature existed, or before a model
was added to config/model_pricing.json / model_pricing_overrides.json, stay
NULL forever unless backfilled — this script does that pass. The same logic
is also exposed as part of `POST /admin/pricing/sync` (runs automatically
after every catalog refresh from the dashboard).

Only touches rows where cost is 0/absent and reference_cost is still NULL, so
re-running after adding new priced models is safe and only fills gaps.

Run inside the ForgeRouter container (needs DATABASE_URL; PYTHONPATH must
include /app since this isn't invoked as `python -m`):
    docker run --rm --network host --env-file .env -e PYTHONPATH=/app \
        forgerouter:latest python3 scripts/backfill_reference_cost.py
"""

from __future__ import annotations

from app.storage import backfill_reference_costs


def main() -> None:
    checked, priced = backfill_reference_costs()
    print(f"{checked} rows checked, {priced} priced, {checked - priced} left without a catalog match")


if __name__ == "__main__":
    main()
