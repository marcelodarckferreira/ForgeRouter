-- xAI Grok (SuperGrok / X Premium+) OAuth subscription adapter. Unlike the
-- other OAuth subscription plans, ForgeRouter itself performs the device-code
-- login (scripts/xai_oauth_login.py) since there is no existing CLI already
-- logged in on the host to lean on. Token lives in ~/.xai/auth.json.
INSERT INTO ai_router.subscription_catalog (name, display_name, plan_hint, base_url, auth_method, token_hint, extra_headers) VALUES
    ('xai-grok-oauth', 'xAI Grok (SuperGrok/X Premium+)', 'Grok CLI proxy via OAuth device-code login', 'https://cli-chat-proxy.grok.com/v1', 'oauth', 'automatic — run scripts/xai_oauth_login.py once, then leave empty (XAI_AUTH_FILE/~/.xai/auth.json)', '{}'::jsonb)
ON CONFLICT (name) DO UPDATE SET display_name = EXCLUDED.display_name, auth_method = EXCLUDED.auth_method, token_hint = EXCLUDED.token_hint, extra_headers = EXCLUDED.extra_headers;
