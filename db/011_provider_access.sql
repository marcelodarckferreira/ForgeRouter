-- Provider access model: how we authenticate (subscription token / api key / local)
-- and whether usage is billed. Subscription particularities (base URL, extra headers,
-- where to get the token) live in auth_config and in the seeded subscription_catalog.
ALTER TABLE ai_router.providers
    ADD COLUMN IF NOT EXISTS access_type TEXT NOT NULL DEFAULT 'api_key',
    ADD COLUMN IF NOT EXISTS cost_type TEXT NOT NULL DEFAULT 'free',
    ADD COLUMN IF NOT EXISTS auth_config JSONB NOT NULL DEFAULT '{}'::jsonb;

DO $$
BEGIN
    ALTER TABLE ai_router.providers
        ADD CONSTRAINT providers_access_type_check CHECK (access_type IN ('subscription', 'api_key', 'local'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    ALTER TABLE ai_router.providers
        ADD CONSTRAINT providers_cost_type_check CHECK (cost_type IN ('free', 'paid'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Existing providers that point at the local machine are local-access.
UPDATE ai_router.providers
SET access_type = 'local'
WHERE base_url LIKE '%127.0.0.1%' OR base_url LIKE '%localhost%' OR base_url LIKE '%host.docker.internal%';

-- Catalog of known subscription providers ("coding plans"): the dashboard lists these
-- when adding a subscription provider. The user signs in on the provider's site, copies
-- the plan token and pastes it (stored in providers.api_key). Editable per deployment.
CREATE TABLE IF NOT EXISTS ai_router.subscription_catalog (
    catalog_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    plan_hint TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL,
    auth_method TEXT NOT NULL DEFAULT 'token',
    token_hint TEXT NOT NULL DEFAULT '',
    extra_headers JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_router.subscription_catalog TO proxyrouter_user;
GRANT USAGE, SELECT ON SEQUENCE ai_router.subscription_catalog_catalog_id_seq TO proxyrouter_user;

INSERT INTO ai_router.subscription_catalog (name, display_name, plan_hint, base_url, auth_method, token_hint) VALUES
    ('subscription_zai', 'Subscription Z.ai', 'Z.ai web free native adapter', 'https://chat.z.ai/api', 'oauth', 'anonymous free token or ~/.zai/auth.json'),
    ('moonshot', 'Moonshot', 'Kimi Coding Plan', 'https://api.moonshot.ai/v1', 'token', 'platform.moonshot.ai → API Keys'),
    ('minimax', 'MiniMax', 'MiniMax Coding Plan', 'https://api.minimax.io/v1', 'token', 'minimax.io → API Keys'),
    ('ollama-cloud', 'Ollama Cloud', 'Ollama Cloud subscription', 'https://ollama.com/v1', 'token', 'ollama.com → Settings → API Keys')
ON CONFLICT (name) DO NOTHING;
