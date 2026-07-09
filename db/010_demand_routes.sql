-- Demand-based routing: ordered model chain per demand class (simple/standard/complex/reasoning).
-- Empty chain for a demand = derive it automatically from the AI rank.
CREATE TABLE IF NOT EXISTS ai_router.demand_routes (
    demand TEXT NOT NULL,
    position INTEGER NOT NULL,
    model_id BIGINT NOT NULL REFERENCES ai_router.models(model_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (demand, position)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_router.demand_routes TO proxyrouter_user;
