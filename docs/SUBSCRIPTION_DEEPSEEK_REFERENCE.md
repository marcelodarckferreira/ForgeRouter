# Subscription DeepSeek Reference

This is the ForgeRouter reference for testing DeepSeek web free as a native
subscription provider. ForgeRouter does not run `ds-free-api` as a sidecar and
does not import that project's code; it implements the same integration concept
internally.

Canonical ForgeRouter identifiers:

```text
provider: subscription_deepseek
base_url: https://chat.deepseek.com/api/v0
auth_method: oauth
auth_file: ~/.deepseek/auth.json
```

## Architecture

```text
Hermes / client
  -> ForgeRouter /v1/chat/completions
  -> DeepSeek web backend
```

ForgeRouter's native DeepSeek adapter can read a DeepSeek web token or login
credentials, create a temporary chat session, solve DeepSeek's web PoW
challenge, call the web completion endpoint, and translate the stream back to
OpenAI-compatible chat completions.

## Auth Model

Provide either a ready bearer token or login credentials through:

```text
~/.deepseek/auth.json
```

Accepted JSON shapes:

```json
{"token": "..."}
```

```json
{"email": "...", "password": "..."}
```

```json
{"mobile": "...", "area_code": "+55", "password": "..."}
```

Equivalent environment variables are also supported:

```text
DEEPSEEK_WEB_TOKEN
DEEPSEEK_WEB_EMAIL
DEEPSEEK_WEB_MOBILE
DEEPSEEK_WEB_AREA_CODE
DEEPSEEK_WEB_PASSWORD
```

The Docker compose files mount this read-only into the container:

```text
~/.deepseek:/root/.deepseek:ro
```

## Register In ForgeRouter

The migration `db/024_subscription_deepseek.sql` adds this subscription catalog
entry:

```text
name: subscription_deepseek
display_name: Subscription DeepSeek
base_url: https://chat.deepseek.com/api/v0
auth_method: oauth
```

Dashboard flow:

1. Open `Routing`.
2. Click `Add provider`.
3. Set `Access` to `Subscription`.
4. Pick `Subscription DeepSeek`.
5. Leave the token field empty if using `~/.deepseek/auth.json` or environment variables.
6. Click `Detect models`.
7. Save and validate.
8. Associate the discovered models with the target ForgeRouter agent.

Expected model ids:

```text
deepseek-default
deepseek-expert
deepseek-vision
```

ForgeRouter stores them publicly as:

```text
subscription_deepseek/deepseek-default
subscription_deepseek/deepseek-expert
subscription_deepseek/deepseek-vision
```

## API Registration Example

```bash
curl -H "Authorization: Bearer <FORGEROUTER_ADMIN_OR_AGENT_TOKEN>" \
  -H "Content-Type: application/json" \
  -X PUT http://127.0.0.1:2100/admin/providers/subscription_deepseek \
  -d '{
    "name": "subscription_deepseek",
    "tier": 2,
    "base_url": "https://chat.deepseek.com/api/v0",
    "api_key": "",
    "enabled": true,
    "access_type": "subscription",
    "cost_type": "free",
    "auth_config": {},
    "models": [
      {
        "id": "subscription_deepseek/deepseek-default",
        "provider_model": "deepseek-default",
        "capabilities": ["text"],
        "enabled": true
      }
    ]
  }'
```

## Smoke Test

After saving and validating the provider:

```bash
curl http://127.0.0.1:2100/v1/chat/completions \
  -H "Authorization: Bearer <FORGEROUTER_AGENT_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "subscription_deepseek/deepseek-default",
    "messages": [{"role": "user", "content": "Reply only OK"}]
  }'
```

Direct subscription-method evaluation:

```bash
docker compose run --rm forgerouter python scripts/subscription_smoke.py --provider deepseek
```
