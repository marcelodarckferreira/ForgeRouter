ALTER TABLE ai_router.providers ADD COLUMN IF NOT EXISTS api_key_env TEXT NOT NULL DEFAULT '';

UPDATE ai_router.providers SET api_key_env = 'GROQ_API_KEY' WHERE name = 'groq' AND api_key_env = '';
UPDATE ai_router.providers SET api_key_env = 'OPENROUTER_API_KEY' WHERE name = 'openrouter' AND api_key_env = '';
UPDATE ai_router.providers SET api_key_env = 'MISTRAL_API_KEY' WHERE name = 'mistral' AND api_key_env = '';
