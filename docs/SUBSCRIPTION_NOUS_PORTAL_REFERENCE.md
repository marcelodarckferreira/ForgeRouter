# Subscription Nous Portal (Hermes Agent) Reference

ForgeRouter reference for Nous Portal — the inference backend behind Hermes
Agent (Nous Research) — as a subscription provider.

Canonical ForgeRouter identifiers:

```text
provider: nous-portal
base_url: https://inference-api.nousresearch.com/v1
auth_method: token
```

## Auth Model — a plain API key, no OAuth adapter

Nous Portal has **no public OAuth authorization server** third-party apps
can register a client against — only a static API key (from
`portal.nousresearch.com` → API Keys), or the Hermes CLI's own proprietary
browser-login flow, which isn't something an external app like ForgeRouter
can safely consume (its resulting credential is an internally refreshed JWT
with a ~2 minute TTL, with no file ForgeRouter could poll the way it does
for Claude Code/Codex/Z.ai). Nous Portal's own documentation recommends the
static API key as the default path for external apps for exactly this
reason.

So `nous-portal` takes the plain `openai`-format, token-based path — no
`app/providers/nous.py`, no entry in `app/providers/plans.py`, no extra
process running on the host — identical to Moonshot/MiniMax/Ollama Cloud.

```text
Hermes / client
  -> ForgeRouter /v1/chat/completions
  -> inference-api.nousresearch.com/v1 (OpenAI-compatible, bearer = API key)
```

## Get an API Key

1. Sign in at `https://portal.nousresearch.com/manage-subscription`.
2. Go to **API Keys** and create one.

## Register In ForgeRouter

The migration `db/044_subscription_nous_portal.sql` adds the catalog entry
and `db/045_nous_portal_api_key.sql` points it at the token-based endpoint:

```text
name: nous-portal
display_name: Nous Portal (Hermes Agent)
base_url: https://inference-api.nousresearch.com/v1
auth_method: token
```

Dashboard flow:

1. Open `Routing`.
2. Click `Add provider`.
3. Set `Access` to `Subscription`.
4. Pick `Nous Portal (Hermes Agent)`.
5. Paste the API key from the step above.
6. Click `Detect models`.
7. Save and validate.
8. Associate the discovered models with the target ForgeRouter agent.

## Public Model IDs

```text
nous-portal/<provider-model-id>
```

## Smoke Test

After saving and validating the provider:

```bash
curl http://127.0.0.1:2100/v1/chat/completions \
  -H "Authorization: Bearer <FORGEROUTER_AGENT_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "nous-portal/<provider-model-id>",
    "messages": [{"role": "user", "content": "Reply only OK"}]
  }'
```
