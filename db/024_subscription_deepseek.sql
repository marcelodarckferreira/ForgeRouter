-- Native DeepSeek web subscription adapter. ForgeRouter logs in to the
-- DeepSeek web backend from local credentials (~/.deepseek/auth.json or
-- DEEPSEEK_WEB_* env vars), solves the provider PoW challenge, and exposes the
-- models through the normal OpenAI-compatible router surface.
INSERT INTO ai_router.subscription_catalog (name, display_name, plan_hint, base_url, auth_method, token_hint, extra_headers) VALUES
    ('subscription_deepseek', 'Subscription DeepSeek', 'DeepSeek web free native adapter', 'https://chat.deepseek.com/api/v0', 'oauth', 'automatic — reads DEEPSEEK_WEB_AUTH_FILE or ~/.deepseek/auth.json (leave empty)', '{}'::jsonb)
ON CONFLICT (name) DO UPDATE SET display_name = EXCLUDED.display_name, plan_hint = EXCLUDED.plan_hint, base_url = EXCLUDED.base_url, auth_method = EXCLUDED.auth_method, token_hint = EXCLUDED.token_hint, extra_headers = EXCLUDED.extra_headers;
