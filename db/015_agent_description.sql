-- Free-text purpose shown on the agent card, set at registration — e.g. mark the
-- agent used by the Hermes auxiliary tasks ("aux" in the name/description makes it
-- the default token on the Tasks page).
ALTER TABLE ai_router.agents ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';
