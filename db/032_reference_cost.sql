-- Notional cost reference: ForgeRouter only routes to free-tier models (paid
-- models are excluded at discovery), so the real `cost` column is almost
-- always 0 — providers rarely report a billed cost for a free model. This
-- column holds what the request would have cost at public commercial rates
-- for an equivalent model (app/pricing.py, vendored LiteLLM catalog), purely
-- as an opportunity-cost estimate. It is only ever computed when `cost` is
-- absent/zero, is NULL when no catalog match exists, and must never be
-- confused with real billed cost in aggregates.
ALTER TABLE ai_router.route_events ADD COLUMN IF NOT EXISTS reference_cost NUMERIC(12, 6);
