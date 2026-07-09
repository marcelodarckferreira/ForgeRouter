-- Lossless context compaction: a generic key/value settings table (so the
-- on/off toggle is changeable from the dashboard without redeploying), plus a
-- column to record the estimated pre-compaction prompt token count per route
-- event so the dashboard can show "tokens saved".
CREATE TABLE IF NOT EXISTS ai_router.settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_router.settings TO proxyrouter_user;

INSERT INTO ai_router.settings (key, value) VALUES ('context_compaction_enabled', 'true')
ON CONFLICT (key) DO NOTHING;

ALTER TABLE ai_router.route_events
    ADD COLUMN IF NOT EXISTS prompt_tokens_raw INTEGER;
