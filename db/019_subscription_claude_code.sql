-- Claude Code (Claude Pro/Max subscription via the `claude` CLI) coding plan
-- in the subscription picker. The Claude Code plan handler
-- (app/providers/plans.py / app/providers/claude_code.py) speaks Anthropic's
-- Messages API (/v1/messages) and resolves the OAuth token from the Claude
-- Code CLI login (~/.claude/.credentials.json, mounted read-only into the
-- container) — the token field can stay empty.
INSERT INTO ai_router.subscription_catalog (name, display_name, plan_hint, base_url, auth_method, token_hint, extra_headers) VALUES
    ('claude-code', 'Claude Code', 'Claude Pro/Max (claude CLI)', 'https://api.anthropic.com/v1', 'oauth', 'automatic — uses the Claude Code (claude) CLI login on the server (leave empty)', '{}'::jsonb)
ON CONFLICT (name) DO UPDATE SET token_hint = EXCLUDED.token_hint, extra_headers = EXCLUDED.extra_headers;
