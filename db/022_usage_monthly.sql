-- Persisted monthly token/message/cost rollup per agent. Lets the "monthly
-- usage by agent" panel on Overview show year-to-date history even after old
-- route_events rows are archived (POST /admin/usage/archive).
CREATE TABLE IF NOT EXISTS ai_router.usage_monthly (
    agent_id BIGINT NOT NULL REFERENCES ai_router.agents(agent_id) ON DELETE CASCADE,
    year SMALLINT NOT NULL,
    month SMALLINT NOT NULL,
    messages BIGINT NOT NULL DEFAULT 0,
    tokens BIGINT NOT NULL DEFAULT 0,
    cost NUMERIC(14,6) NOT NULL DEFAULT 0,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (agent_id, year, month)
);
