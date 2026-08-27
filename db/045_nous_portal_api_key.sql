-- Simplify Nous Portal to a plain API-key subscription plan. db/044 pointed
-- this at a local `hermes proxy` credential-broker process on the host — a
-- real OAuth bridge, but one that needs an extra always-running host service
-- (systemd unit, no auth of its own) just to avoid pasting a key. Nous
-- Portal's own docs recommend the API key as the default path for external
-- apps anyway (portal.nousresearch.com -> API Keys), and it's simple: no
-- proxy, no systemd, no adapter code — same pattern as Moonshot/MiniMax.
UPDATE ai_router.subscription_catalog SET
    plan_hint = 'Nous Portal subscription',
    base_url = 'https://inference-api.nousresearch.com/v1',
    auth_method = 'token',
    token_hint = 'portal.nousresearch.com → API Keys'
WHERE name = 'nous-portal';
