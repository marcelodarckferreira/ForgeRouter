-- Per-agent provider/model controls. An agent with no rows here may use every model;
-- once models are associated, routing for that agent is restricted to them.
-- Keyed by agent_id, so rotating the agent's API key never loses these controls.
CREATE TABLE IF NOT EXISTS ai_router.agent_models (
    agent_id BIGINT NOT NULL REFERENCES ai_router.agents(agent_id) ON DELETE CASCADE,
    model_id BIGINT NOT NULL REFERENCES ai_router.models(model_id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, model_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_router.agent_models TO proxyrouter_user;
