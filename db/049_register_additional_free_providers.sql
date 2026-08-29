-- Seed new popular free-tier/serverless providers from the free LLM ecosystem.
-- Registered as disabled by default so users can provide their API keys before enabling.
INSERT INTO ai_router.providers (name, base_url, tier, access_type, cost_type, api_format, enabled)
VALUES
    ('huggingface', 'https://api-inference.huggingface.co/v1', 3, 'api_key', 'free', 'openai', false),
    ('modelscope', 'https://api-inference.modelscope.cn/v1', 3, 'api_key', 'free', 'openai', false),
    ('siliconflow', 'https://api.siliconflow.cn/v1', 3, 'api_key', 'free', 'openai', false),
    ('together', 'https://api.together.xyz/v1', 3, 'api_key', 'free', 'openai', false),
    ('fireworks', 'https://api.fireworks.ai/inference/v1', 3, 'api_key', 'free', 'openai', false),
    ('hyperbolic', 'https://api.hyperbolic.xyz/v1', 3, 'api_key', 'free', 'openai', false),
    ('deepinfra', 'https://api.deepinfra.com/v1/openai', 3, 'api_key', 'free', 'openai', false)
ON CONFLICT (name) DO UPDATE
SET base_url = EXCLUDED.base_url;

INSERT INTO ai_router.providers (name, base_url, tier, access_type, cost_type, api_format, enabled)
VALUES
    ('ovhcloud', 'https://oai.endpoints.kepler.ai.cloud.ovh.net/v1', 3, 'api_key', 'free', 'openai', false),
    ('novita', 'https://api.novita.ai/openai/v1', 3, 'api_key', 'free', 'openai', false),
    ('pollinations', 'https://text.pollinations.ai/openai', 3, 'api_key', 'free', 'openai', false)
ON CONFLICT (name) DO UPDATE
SET base_url = EXCLUDED.base_url;
