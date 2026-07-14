#!/usr/bin/env python
"""Refresh config/model_pricing.json from LiteLLM's public price catalog.

app/pricing.py estimates a notional/opportunity-cost value for free-tier
requests (see its docstring). The catalog is a vendored snapshot, not a live
fetch, so it drifts out of date as LiteLLM updates prices — re-run this
occasionally to refresh it.

This is the LiteLLM-catalog step only. For the full sync (LiteLLM catalog +
live provider /models pricing + historical backfill — the same three steps
as clicking Sync in the dashboard, or POST /admin/pricing/sync), use
scripts/sync_pricing.py instead; that's also the one to put in cron.

    python3 scripts/update_pricing.py

Only chat-capable entries with a numeric input/output cost per token are
kept; image/audio/embedding/rerank modes and entries missing token pricing
are dropped. config/model_pricing_overrides.json (hand-curated entries) is
untouched by this script.
"""

from __future__ import annotations

from app.pricing import _CATALOG_PATH, sync_catalog_from_litellm


def main() -> None:
    count = sync_catalog_from_litellm()
    print(f"Wrote {count} chat-model price entries to {_CATALOG_PATH}")


if __name__ == "__main__":
    main()
