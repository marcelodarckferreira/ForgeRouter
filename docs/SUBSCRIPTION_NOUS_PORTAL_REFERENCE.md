# Subscription Nous Portal (Hermes Agent) Reference

ForgeRouter reference for Nous Portal — the inference backend behind Hermes
Agent (Nous Research) — as an OAuth subscription provider.

Canonical ForgeRouter identifiers:

```text
provider: nous-portal
base_url: http://host.docker.internal:8645/v1
auth_method: oauth
```

## Architecture — the one adapter-less exception

Every other OAuth subscription provider in this codebase (Claude Code,
Codex, Antigravity, Z.ai, DeepSeek, xAI Grok) has a dedicated
`app/providers/*.py` module that either reads a token file an external CLI
keeps fresh, or performs the OAuth login itself. Nous Portal has neither
option available to it:

- Nous Portal (`inference-api.nousresearch.com`) has **no public OAuth
  authorization server** third-party apps can register a client against —
  only a static API key, or the Hermes CLI's own proprietary browser-login
  flow (`hermes portal`), whose resulting credential is an internally
  refreshed JWT with a short (~2 minute) TTL. There is no file ForgeRouter
  can safely poll the way it does for `~/.codex`/`~/.claude`/`~/.zai`.
- **A static Portal API key was tried first (db/045) and reverted
  (db/046): generating one requires its own prepaid credit — it does not
  draw from the subscription's included/free usage.** The subscription's
  free usage is only reachable through the account's Portal login, i.e.
  through the Hermes CLI.
- The Hermes Agent project's own documentation for this exact scenario
  (`skills/autonomous-ai-agents/hermes-agent/references/portal-auth-for-third-party-apps.md`
  in the `hermes-agent` package) prescribes a **local credential-broker
  proxy** as the supported bridge: `hermes proxy start --provider nous`,
  shipped with the Hermes CLI, exposes a local OpenAI-compatible endpoint
  that injects a live Nous bearer (from the CLI's own logged-in Portal
  session, i.e. the subscription's included usage) into every request.
  External apps point at it with *any* placeholder token.

So `nous-portal` takes the plain `openai`-format path — no
`app/providers/nous.py`, no entry in `app/providers/plans.py` — identical
to how Z.ai/Moonshot/MiniMax/Ollama Cloud need no dedicated handler. All
the OAuth complexity is delegated to the already-shipped `hermes proxy`
process running on the host, outside this repo and outside Docker.

```text
Hermes / client
  -> ForgeRouter /v1/chat/completions
  -> hermes proxy (host, 172.20.0.1:8645, no auth of its own)
  -> inference-api.nousresearch.com/v1 (real Nous bearer attached,
     drawing from the Portal subscription's included usage)
```

## Host Setup (outside this repo)

1. Log in once, interactively (opens a browser):

   ```bash
   hermes portal
   ```

2. Run the credential-broker proxy as a persistent service — systemd unit
   `/etc/systemd/system/hermes-proxy-nous.service` (mirrors the existing
   `hermes-serve.service` pattern):

   ```ini
   ExecStart=/usr/local/lib/hermes-agent/venv/bin/python -m hermes_cli.main proxy start --provider nous --host 172.20.0.1 --port 8645
   Environment="HERMES_HOME=/root/.hermes"
   ```

   Bound to the `foundation_network` Docker bridge gateway address
   (`172.20.0.1`, the same address `host.docker.internal` resolves to for
   containers on that network via the `extra_hosts: host-gateway` mapping
   in `docker-compose.yml`) — **not** `0.0.0.0`. `hermes proxy` has no
   authentication of its own, so binding it to every interface would let
   anything that can reach this host use the operator's live Nous
   subscription.

   ```bash
   systemctl daemon-reload
   systemctl enable --now hermes-proxy-nous.service
   systemctl status hermes-proxy-nous.service
   ```

3. Unlike every other subscription adapter here, **nothing is mounted into
   the ForgeRouter container** — the container reaches the proxy over the
   network (`host.docker.internal:8645`), not a filesystem credential.

If the systemd unit isn't running (or the operator hasn't logged in via
`hermes portal`), `nous-portal` requests fail like any other unhealthy
provider — ForgeRouter's normal fallback covers it, no special-casing
needed.

## Register In ForgeRouter

The migration `db/044_subscription_nous_portal.sql` adds this subscription
catalog entry, `db/045` briefly pointed it at a plain API key (reverted —
see above), and `db/046_nous_portal_revert_to_oauth_proxy.sql` restores the
proxy-based settings:

```text
name: nous-portal
display_name: Nous Portal (Hermes Agent)
base_url: http://host.docker.internal:8645/v1
auth_method: oauth
```

Dashboard flow (after the host setup above):

1. Open `Routing`.
2. Click `Add provider`.
3. Set `Access` to `Subscription`.
4. Pick `Nous Portal (Hermes Agent)`.
5. The token field can be left as any placeholder value (e.g. `nous`) —
   `hermes proxy` ignores it and attaches the real credential itself.
6. Click `Detect models` — Nous Portal exposes a real `/v1/models`, so
   discovery works the same as any plain OpenAI-compatible provider.
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
