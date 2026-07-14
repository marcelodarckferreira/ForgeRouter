-- Optional per-agent monthly budget guard. NULL budget_limit_usd (the
-- default) means no limit — opt-in, existing agents are unaffected until
-- someone sets one. budget_action controls what happens once the agent's
-- current-calendar-month spend (real cost + reference_cost combined, since
-- real cost is almost always 0 on a free-tier-only router) reaches the
-- limit: 'alert' only flags it on the dashboard, 'block' also makes
-- /v1/chat/completions (and the /v1/messages, /v1/responses translators
-- that sit in front of it) return 429 budget_exceeded instead of routing.
ALTER TABLE ai_router.agents
    ADD COLUMN IF NOT EXISTS budget_limit_usd NUMERIC(12, 2),
    ADD COLUMN IF NOT EXISTS budget_action TEXT NOT NULL DEFAULT 'alert';

ALTER TABLE ai_router.agents DROP CONSTRAINT IF EXISTS agents_budget_action_check;
ALTER TABLE ai_router.agents ADD CONSTRAINT agents_budget_action_check CHECK (budget_action IN ('alert', 'block'));
