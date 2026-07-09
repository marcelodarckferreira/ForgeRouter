-- Durable agent ↔ provider participation. Refresh / Run scan sync every agent's
-- model list from this table, so replacing a provider's whole model catalog can
-- never silently detach the agents that use it. Seeded from current associations.
CREATE TABLE IF NOT EXISTS ai_router.agent_providers (
    agent_id BIGINT NOT NULL REFERENCES ai_router.agents(agent_id) ON DELETE CASCADE,
    provider_id BIGINT NOT NULL REFERENCES ai_router.providers(provider_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, provider_id)
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_router.agent_providers TO proxyrouter_user;

INSERT INTO ai_router.agent_providers (agent_id, provider_id)
SELECT DISTINCT am.agent_id, m.provider_id
FROM ai_router.agent_models am
JOIN ai_router.models m ON m.model_id = am.model_id
ON CONFLICT DO NOTHING;
