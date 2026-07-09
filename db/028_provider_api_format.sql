-- Provider API format: the wire protocol the provider endpoint speaks.
-- openai = OpenAI-compatible POST /chat/completions (the default);
-- anthropic = Anthropic Messages API POST /v1/messages.
-- All pre-existing providers are OpenAI-compatible, so the default backfills them.
ALTER TABLE ai_router.providers
    ADD COLUMN IF NOT EXISTS api_format TEXT NOT NULL DEFAULT 'openai';

DO $$
BEGIN
    ALTER TABLE ai_router.providers
        ADD CONSTRAINT providers_api_format_check CHECK (api_format IN ('openai', 'anthropic'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
