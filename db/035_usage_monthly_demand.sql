-- Persisted monthly rollup per demand class, mirroring usage_monthly (db/022) but
-- keyed by demand instead of agent. Lets a "monthly usage by demand" panel survive
-- archival of old route_events (POST /admin/usage/archive), same as the per-agent
-- one. Requests without a demand (a concrete model id was requested, no forgerouter/
-- auto classification) are not rolled up here — this table is demand-routing-only.
CREATE TABLE IF NOT EXISTS ai_router.usage_monthly_demand (
    demand TEXT NOT NULL,
    year SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    messages BIGINT NOT NULL DEFAULT 0,
    tokens BIGINT NOT NULL DEFAULT 0,
    cost NUMERIC(14,6) NOT NULL DEFAULT 0,
    reference_cost NUMERIC(14,6) NOT NULL DEFAULT 0,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (demand, year, month)
);
