-- Z.ai remains OpenAI-compatible, but ForgeRouter can now resolve the
-- credential from a local OAuth/session file (~/.zai/auth.json) instead of a
-- pasted API key. The operator is still responsible for obtaining that file via
-- an approved Z.ai login/CLI flow; ForgeRouter does not automate web login.
INSERT INTO ai_router.subscription_catalog (name, display_name, plan_hint, base_url, auth_method, token_hint, extra_headers) VALUES
    ('subscription_zai', 'Subscription Z.ai', 'Z.ai web free native adapter', 'https://chat.z.ai/api', 'oauth', 'automatic — anonymous free token or ZAI_AUTH_FILE/~/.zai/auth.json (leave empty)', '{}'::jsonb)
ON CONFLICT (name) DO UPDATE SET display_name = EXCLUDED.display_name, auth_method = EXCLUDED.auth_method, token_hint = EXCLUDED.token_hint, extra_headers = EXCLUDED.extra_headers;

DELETE FROM ai_router.subscription_catalog WHERE name = 'zai';
