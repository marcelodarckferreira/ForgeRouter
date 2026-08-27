-- Nous Portal (Hermes Agent) subscription plan. Unlike every other OAuth
-- adapter in this codebase, ForgeRouter does not talk to the upstream
-- directly or parse any auth file itself: Nous Portal has no public OAuth
-- authorization server third-party apps can register against (only a static
-- API key or the Hermes CLI's own proprietary browser-login flow). The
-- documented, first-party-endorsed bridge for external apps is `hermes proxy`
-- (ships with the Hermes Agent CLI) — a local OpenAI-compatible broker that
-- reads/refreshes the operator's Nous Portal credential from
-- ~/.hermes/auth.json and forwards with a real bearer attached. Point this
-- provider's base_url at that local proxy and any placeholder token works;
-- no dedicated app/providers/nous.py handler is needed, same as Z.ai/
-- Moonshot/MiniMax/Ollama Cloud.
INSERT INTO ai_router.subscription_catalog (name, display_name, plan_hint, base_url, auth_method, token_hint, auth_url, extra_headers) VALUES
    ('nous-portal', 'Nous Portal (Hermes Agent)', 'Nous subscription via the Hermes CLI credential-broker proxy', 'http://host.docker.internal:8645/v1', 'oauth', 'placeholder — run `hermes portal` once to log in, then `hermes proxy start --provider nous --host 0.0.0.0 --port 8645` (kept running, e.g. as a systemd unit); the proxy injects the real credential', 'https://portal.nousresearch.com/manage-subscription', '{}'::jsonb)
ON CONFLICT (name) DO UPDATE SET display_name = EXCLUDED.display_name, plan_hint = EXCLUDED.plan_hint, base_url = EXCLUDED.base_url, auth_method = EXCLUDED.auth_method, token_hint = EXCLUDED.token_hint, auth_url = EXCLUDED.auth_url, extra_headers = EXCLUDED.extra_headers;
