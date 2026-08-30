-- Google Antigravity authenticates via the agy CLI token file on the server
-- (~/.gemini/antigravity-cli/antigravity-oauth-token), not via a web login URL.
-- Clear auth_url so the dashboard does not show a misleading external auth link.
UPDATE ai_router.subscription_catalog
SET auth_url = ''
WHERE name = 'google-antigravity';
