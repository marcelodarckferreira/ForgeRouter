-- Agents: each connected agent (e.g. Athos, Opencode) authenticates with its own API key.
CREATE TABLE IF NOT EXISTS ai_router.agents (
    agent_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    api_key TEXT NOT NULL UNIQUE,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Attribute each routed request to the agent whose key was on the Authorization header.
ALTER TABLE ai_router.route_events
    ADD COLUMN IF NOT EXISTS agent_id BIGINT REFERENCES ai_router.agents(agent_id) ON DELETE SET NULL;

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_router.agents TO proxyrouter_user;
GRANT USAGE, SELECT ON SEQUENCE ai_router.agents_agent_id_seq TO proxyrouter_user;
