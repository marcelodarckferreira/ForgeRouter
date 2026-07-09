-- Google Antigravity (Gemini Code Assist / agy CLI) coding plan in the
-- subscription picker. The Antigravity plan handler (app/providers/plans.py)
-- speaks Google's internal Cloud Code Assist API (generateContent /
-- streamGenerateContent) and resolves the OAuth token from the Antigravity
-- CLI login (~/.gemini/antigravity-cli/antigravity-oauth-token, mounted
-- read-only into the container) — the token field can stay empty.
INSERT INTO ai_router.subscription_catalog (name, display_name, plan_hint, base_url, auth_method, token_hint, extra_headers) VALUES
    ('google-antigravity', 'Google Antigravity', 'Gemini Code Assist (agy CLI)', 'https://cloudcode-pa.googleapis.com/v1internal', 'oauth', 'automatic — uses the Antigravity (agy) CLI login on the server (leave empty)', '{}'::jsonb)
ON CONFLICT (name) DO UPDATE SET token_hint = EXCLUDED.token_hint, extra_headers = EXCLUDED.extra_headers;
