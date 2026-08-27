-- Re-simplify Nous Portal to a plain API key (undoes db/046). Confirmed with
-- the operator: Nous Portal requires topping up account credit before any
-- inference works at all — that requirement applies identically to a static
-- API key and to the `hermes proxy` OAuth broker, since both hit the same
-- billed account. There is no free tier the OAuth path reaches that the API
-- key doesn't, so the extra host-level proxy/systemd process buys nothing
-- and the simple, adapter-less path (same as Moonshot/MiniMax/Ollama Cloud)
-- is strictly better.
UPDATE ai_router.subscription_catalog SET
    plan_hint = 'Nous Portal subscription',
    base_url = 'https://inference-api.nousresearch.com/v1',
    auth_method = 'token',
    token_hint = 'portal.nousresearch.com → API Keys (requires topping up account credit first)'
WHERE name = 'nous-portal';
