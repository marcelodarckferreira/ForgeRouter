-- Provider-owned authentication/account destinations for subscription plans.
-- These links are catalog data so the dashboard does not hardcode provider
-- names or URLs. They are explicit navigation only; selecting a plan never
-- opens a popup automatically.
ALTER TABLE ai_router.subscription_catalog
    ADD COLUMN IF NOT EXISTS auth_url TEXT NOT NULL DEFAULT '';

UPDATE ai_router.subscription_catalog SET auth_url = CASE name
    WHEN 'openai-codex' THEN 'https://chatgpt.com/auth/login/'
    WHEN 'claude-code' THEN 'https://claude.ai/login'
    WHEN 'google-antigravity' THEN 'https://antigravity.google/'
    WHEN 'subscription_zai' THEN 'https://chat.z.ai/auth'
    WHEN 'minimax' THEN 'https://platform.minimax.io/'
    WHEN 'moonshot' THEN 'https://app.moonshot-ai.com/'
    WHEN 'ollama-cloud' THEN 'https://ollama.com/settings/keys'
    WHEN 'subscription_deepseek' THEN 'https://chat.deepseek.com/'
    WHEN 'xai-grok-oauth' THEN 'https://accounts.x.ai/sign-in?redirect=grok-app'
    ELSE auth_url
END
WHERE auth_url = '';
