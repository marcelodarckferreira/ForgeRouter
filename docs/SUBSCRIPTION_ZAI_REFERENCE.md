# Subscription Z.ai Reference

This is the ForgeRouter reference for testing Z.ai as a subscription provider.

Canonical ForgeRouter identifiers:

```text
provider: subscription_zai
base_url: https://chat.z.ai/api
auth_method: oauth
auth_file: ~/.zai/auth.json
```

## Architecture

```text
Hermes / client
  -> ForgeRouter /v1/chat/completions
  -> Z.ai web chat endpoint
```

ForgeRouter implements the Z.ai web adapter natively: it can fetch an anonymous
free token, sign requests, call the Z.ai web chat endpoint, and translate the
stream back to OpenAI-compatible chat completions.

Current operational note: Z.ai may return `FRONTEND_CAPTCHA_REQUIRED` for
anonymous web completion requests. ForgeRouter reports that upstream error
explicitly; it does not bypass captchas or extract private browser cookies.

## Auth Model

ForgeRouter does not capture browser cookies or Google OAuth redirects from
`https://z.ai/chat`.

The default no-API-key path is the anonymous free token. To use your logged-in
account instead, provide a local token file:

```text
~/.zai/auth.json
```

Accepted JSON shapes:

```json
{"access_token": "..."}
```

```json
{"tokens": {"access_token": "..."}}
```

The Docker compose files mount this read-only into the container:

```text
~/.zai:/root/.zai:ro
```

## Register In ForgeRouter

The migration `db/023_subscription_zai_oauth.sql` adds this subscription catalog
entry:

```text
name: subscription_zai
display_name: Subscription Z.ai
base_url: https://chat.z.ai/api
auth_method: oauth
```

Dashboard flow:

1. Open `Routing`.
2. Click `Add provider`.
3. Set `Access` to `Subscription`.
4. Pick `Subscription Z.ai`.
5. Leave the token field empty for anonymous free mode.
6. Optional: ensure `~/.zai/auth.json` exists and is readable by the container for a logged-in account token.
7. Click `Detect models`.
8. Save and validate.
9. Associate the discovered models with the target ForgeRouter agent.

## Check Auth

```bash
cd /root/.hermes/forgerouter
docker compose run --rm forgerouter python scripts/zai_oauth_check.py
```

Expected success:

```json
{
  "status": "ok",
  "auth_file": "/root/.zai/auth.json",
  "token_shape": "jwt",
  "models": ["..."]
}
```

If it reports `missing_token`, anonymous auth failed and no local token file was found.

## Public Model IDs

Discovered models are stored with the provider prefix:

```text
subscription_zai/<provider-model-id>
```

Example:

```text
subscription_zai/glm-5
```

## Smoke Test

After saving and validating the provider:

```bash
curl http://127.0.0.1:2100/v1/chat/completions \
  -H "Authorization: Bearer <FORGEROUTER_AGENT_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "subscription_zai/glm-5",
    "messages": [{"role": "user", "content": "Reply only OK"}]
  }'
```

Direct subscription-method evaluation:

```bash
docker compose run --rm forgerouter python scripts/subscription_smoke.py --provider zai
```
