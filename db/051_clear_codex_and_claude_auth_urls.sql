-- Remove auth_url for openai-codex and claude-code: both authenticate automatically
-- via CLI (codex and claude) on the host machine, matching google-antigravity.
UPDATE ai_router.subscription_catalog
SET auth_url = ''
WHERE name IN ('openai-codex', 'claude-code');
