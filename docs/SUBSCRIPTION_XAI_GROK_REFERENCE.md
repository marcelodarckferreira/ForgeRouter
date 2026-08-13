# Subscription xAI Grok (SuperGrok / X Premium+) Reference

ForgeRouter reference for xAI Grok as an OAuth subscription provider, using a
SuperGrok or X Premium+ personal subscription instead of a billed `XAI_API_KEY`.

Canonical ForgeRouter identifiers:

```text
provider: xai-grok-oauth
base_url: https://cli-chat-proxy.grok.com/v1
auth_method: oauth
auth_file: ~/.xai/auth.json
```

## Architecture

```text
Hermes / client
  -> ForgeRouter /v1/chat/completions
  -> Grok CLI proxy (cli-chat-proxy.grok.com/v1/responses, OpenAI Responses API shape)
```

OAuth-authenticated Grok access does not go through the public,
api-key-billed `api.x.ai/v1` — it rides a dedicated CLI proxy speaking the
same streaming-only OpenAI Responses API shape `openai-codex` uses.
`app/providers/xai_grok.py` translates chat-completions requests into
Responses payloads and folds (or re-streams) the response back, mirroring
`app/providers/codex.py`.

## Auth Model — the one deliberate exception

Every other OAuth subscription provider in this codebase (Claude Code, Codex,
Antigravity, Z.ai) only *reads* a token file that some other already-installed
CLI (`claude`, `codex`, `agy`) keeps fresh — ForgeRouter never performs the
login itself. xAI has no equivalent first-party CLI, so `scripts/xai_oauth_login.py`
is the one script in this codebase that runs an OAuth login (the 2.0
device-authorization grant against `auth.x.ai`), and `xai_grok_token()` in
`app/providers/xai_grok.py` refreshes the access token itself before it
expires (rewriting the auth file), instead of relying on an external process.

The device-code endpoints, client_id and scopes are not xAI's own published
third-party docs (xAI does not publish any) — they come from the reference
implementation the ecosystem has converged on (Hermes Agent's `xai-oauth`,
and downstream OAuth clients like `pi-grok`, `opencode-grok-auth`).

## Login

```bash
docker compose run --rm -e PYTHONPATH=/app forgerouter python scripts/xai_oauth_login.py
```

This prints a verification URL (and code, if the URL doesn't embed it) —
open it in any browser (does not need to be this machine) and approve. The
script polls until approved and writes `~/.xai/auth.json`.

**Known limitation:** xAI has been reported to return `403` on this OAuth
surface for some SuperGrok subscribers despite an active subscription (an
account-side allowlist, not something this client controls). If that
happens, the fallback is a plain `XAI_API_KEY` provider (console.x.ai,
`api.x.ai/v1`, OpenAI-compatible, no OAuth) instead.

The Docker compose files should mount the auth directory read-only into the
container, matching the other subscription adapters:

```text
~/.xai:/root/.xai:ro
```

## Register In ForgeRouter

The migration `db/041_subscription_xai_grok_oauth.sql` adds this subscription
catalog entry:

```text
name: xai-grok-oauth
display_name: xAI Grok (SuperGrok/X Premium+)
base_url: https://cli-chat-proxy.grok.com/v1
auth_method: oauth
```

Dashboard flow (after a successful login above):

1. Open `Routing`.
2. Click `Add provider`.
3. Set `Access` to `Subscription`.
4. Pick `xAI Grok (SuperGrok/X Premium+)`.
5. Leave the token field empty — it resolves from `~/.xai/auth.json`.
6. Click `Detect models`.
7. Save and validate.
8. Associate the discovered models with the target ForgeRouter agent.

## Public Model IDs

```text
xai-grok-oauth/<provider-model-id>
```

Example:

```text
xai-grok-oauth/grok-4.5
```

## Smoke Test

After saving and validating the provider:

```bash
curl http://127.0.0.1:2100/v1/chat/completions \
  -H "Authorization: Bearer <FORGEROUTER_AGENT_KEY>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "xai-grok-oauth/grok-4.5",
    "messages": [{"role": "user", "content": "Reply only OK"}]
  }'
```
