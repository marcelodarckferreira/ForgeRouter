-- Classify each registered agent as a real conversational Hermes agent vs an
-- internal service that only needs a routing identity/API key (e.g. Hindsight,
-- which is not a Hermes profile — no gateway, no Telegram, no knowledge base —
-- just a caller that needed a valid key once agent-gated auth activated).
ALTER TABLE ai_router.agents ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'agent';
ALTER TABLE ai_router.agents DROP CONSTRAINT IF EXISTS agents_kind_check;
ALTER TABLE ai_router.agents ADD CONSTRAINT agents_kind_check CHECK (kind IN ('agent', 'service'));

UPDATE ai_router.agents SET kind = 'service' WHERE name = 'Hindsight';
