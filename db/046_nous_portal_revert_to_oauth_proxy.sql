-- Revert db/045: a static Nous Portal API key requires its own prepaid
-- credit — it does NOT draw from the Portal subscription's included/free
-- usage. The subscription's free usage is only reachable through the
-- Hermes CLI's own Portal login (`hermes portal`), so nous-portal goes back
-- to the local hermes-proxy credential-broker approach from db/044.
UPDATE ai_router.subscription_catalog SET
    plan_hint = 'Nous subscription via the Hermes CLI credential-broker proxy',
    base_url = 'http://host.docker.internal:8645/v1',
    auth_method = 'oauth',
    token_hint = 'placeholder — run `hermes portal` once to log in, then `hermes proxy start --provider nous --host 172.20.0.1 --port 8645` (kept running, e.g. as a systemd unit); the proxy injects the real credential'
WHERE name = 'nous-portal';
