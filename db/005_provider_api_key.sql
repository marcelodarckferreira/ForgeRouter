ALTER TABLE ai_router.providers ADD COLUMN IF NOT EXISTS api_key TEXT NOT NULL DEFAULT '';

-- Repair rows where an actual secret was pasted into api_key_env (env var names are
-- strictly uppercase identifiers); move the value to api_key and clear the env field.
UPDATE ai_router.providers
SET api_key = api_key_env, api_key_env = ''
WHERE api_key_env <> '' AND api_key_env !~ '^[A-Z][A-Z0-9_]*$';
