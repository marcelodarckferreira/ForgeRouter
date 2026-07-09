-- OpenAI Codex coding plan (ChatGPT Plus/Pro subscription) in the subscription
-- picker. The Codex plan handler (app/providers/plans.py) speaks the Responses
-- API and resolves the OAuth token from the Codex CLI login (~/.codex/auth.json,
-- mounted read-only into the container) — the token field can stay empty.
INSERT INTO ai_router.subscription_catalog (name, display_name, plan_hint, base_url, auth_method, token_hint, extra_headers) VALUES
    ('openai-codex', 'OpenAI Codex', 'ChatGPT Plus/Pro plan', 'https://chatgpt.com/backend-api/codex', 'oauth', 'automatic — uses the Codex CLI login on the server (leave empty)', '{}'::jsonb)
ON CONFLICT (name) DO UPDATE SET token_hint = EXCLUDED.token_hint, extra_headers = EXCLUDED.extra_headers;
