INSERT INTO ai_router.providers (name, tier, base_url, enabled)
VALUES
  ('local', 4, 'http://127.0.0.1:11434/v1', true),
  ('groq', 1, 'https://api.groq.com/openai/v1', true),
  ('openrouter', 2, 'https://openrouter.ai/api/v1', true),
  ('mistral', 2, 'https://api.mistral.ai/v1', true)
ON CONFLICT (name) DO UPDATE SET tier = EXCLUDED.tier, base_url = EXCLUDED.base_url, enabled = EXCLUDED.enabled;

INSERT INTO ai_router.models (provider_id, public_id, provider_model, capabilities, enabled, healthy)
SELECT p.provider_id, v.public_id, v.provider_model, v.capabilities, true, false
FROM ai_router.providers p
JOIN (
  VALUES
    ('local', 'local/qwen2.5:1.5b', 'qwen2.5:1.5b', ARRAY['text','tool_call']),
    ('local', 'local/llama3.2:1b', 'llama3.2:1b', ARRAY['text']),
    ('local', 'local/qwen2.5:0.5b', 'qwen2.5:0.5b', ARRAY['text']),
    ('groq', 'groq/llama-3.1-8b-instant', 'llama-3.1-8b-instant', ARRAY['text','tool_call']),
    ('openrouter', 'openrouter/meta-llama/llama-3.2-3b-instruct:free', 'meta-llama/llama-3.2-3b-instruct:free', ARRAY['text']),
    ('openrouter', 'openrouter/qwen/qwen-2.5-7b-instruct:free', 'qwen/qwen-2.5-7b-instruct:free', ARRAY['text']),
    ('mistral', 'mistral/mistral-small-latest', 'mistral-small-latest', ARRAY['text','tool_call'])
) AS v(provider_name, public_id, provider_model, capabilities) ON v.provider_name = p.name
ON CONFLICT (public_id) DO UPDATE SET
  provider_id = EXCLUDED.provider_id,
  provider_model = EXCLUDED.provider_model,
  capabilities = EXCLUDED.capabilities,
  enabled = EXCLUDED.enabled;
