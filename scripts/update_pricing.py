#!/usr/bin/env python
"""Refresh config/model_pricing.json from LiteLLM's public price catalog.

app/pricing.py estimates a notional/opportunity-cost value for free-tier
requests (see its docstring). The catalog is a vendored snapshot, not a live
fetch, so it drifts out of date as LiteLLM updates prices — re-run this
occasionally to refresh it. The same logic is also exposed as
`POST /admin/pricing/sync` (app/pricing.py::sync_catalog_from_litellm) for
refreshing from the dashboard instead of the CLI.

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
