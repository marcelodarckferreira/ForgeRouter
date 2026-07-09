# ForgeRouter

Hermes ForgeRouter project.

## Current runtime

The project is currently containerized because the host Python runtime does not expose the required FastAPI/Pytest dependencies reliably.

## Commands

Build image:

```bash
docker compose build
```

Run tests inside container image:

```bash
docker compose run --rm proxyrouter-api pytest -q
```

Run service directly:

```bash
docker rm -f proxyrouter-api 2>/dev/null || true
docker run -d --name proxyrouter-api   --env-file /root/.hermes/forgerouter/.env   -p 127.0.0.1:2100:2100   --restart unless-stopped   proxyrouter-proxyrouter-api:latest
```

Health check:

```bash
curl http://127.0.0.1:2100/health
```

## Database

PostgreSQL database created in the Foundation PostgreSQL instance:

- database: `proxyrouter`
- user: `proxyrouter_user`
- schema: `ai_router`

The `.env` file points to the `proxyrouter` database and must not be committed.

## Provider scanner

Run provider health scanner:

```bash
docker compose run --rm proxyrouter-api python -m app.validation.scanner
```

Current expected behavior until provider credentials/local runtime are wired:
- `local/qwen2.5:1.5b` may return `ConnectError` if Ollama is not reachable from the container.
- `mistral/mistral-small-latest` returns `http_401` if `MISTRAL_API_KEY` is not present in the container env.

The router must not route to providers marked unhealthy.

## Local Ollama note

Ollama on this host listens on `127.0.0.1:11434`, so bridge-network containers cannot reach it through `host.docker.internal`.

For local-provider validation and chat execution, run ForgeRouter with host networking:

```bash
docker rm -f proxyrouter-api 2>/dev/null || true
docker run -d --network host --name proxyrouter-api \
  --env-file /root/.hermes/forgerouter/.env \
  --restart unless-stopped \
  proxyrouter-proxyrouter-api:latest
```

Run scanner with host networking:

```bash
docker run --rm --network host --env-file /root/.hermes/forgerouter/.env \
proxyrouter-proxyrouter-api:latest \
  python -m app.validation.scanner --persist
```

## Admin provider health

Latest provider health endpoint:

```bash
curl http://127.0.0.1:2100/admin/providers/health
```

Returns latest persisted health from `ai_router.provider_health`, with a YAML fallback when the database is unavailable.

## Route events

Every successful or failed provider execution attempts to persist a route event in:

```text
ai_router.route_events
```

Useful query:

```bash
docker exec hermes_foundation_pg_postgres psql -U foundation -d proxyrouter -c "\
SELECT r.route_id, m.public_id, r.required_capability, r.status, r.error_type, r.created_at \
FROM ai_router.route_events r \
LEFT JOIN ai_router.models m ON m.model_id = r.selected_model_id \
ORDER BY r.route_id DESC LIMIT 10;"
```

## Frontend dashboard

Frontend source lives in:

```text
/root/.hermes/forgerouter/frontend
```

Stack:
- React
- Vite
- TypeScript strict
- CSS dashboard style inspired by Linear/Vercel

Commands:

```bash
cd /root/.hermes/forgerouter/frontend
npm install
npm run build
npm run dev
```

Current dashboard reads:

```text
/admin/providers/health
```

The dashboard authorizes admin actions with its login session; API callers use a registered agent's key.

## Scanner scheduling recommendation

Validated manual scanner script:

```bash
/root/.hermes/forgerouter/scripts/forgerouter_scan.sh
```

Recommended schedule after approval:
- every 5 minutes during development; or
- every 15 minutes for low-noise local operation.

Do not schedule before deciding the notification/noise policy.

## Admin routes endpoint

Recent route events endpoint:

```bash
curl http://127.0.0.1:2100/admin/routes/recent
curl 'http://127.0.0.1:2100/admin/routes/recent?limit=10'
```

## Served dashboard

FastAPI serves the built dashboard at:

```text
http://127.0.0.1:2100/
```

The Docker image copies `frontend/dist` into `/app/frontend/dist`. Rebuild the frontend before rebuilding the Docker image when UI changes.

## Active scanner cron

Hermes cron job created:

```text
job_id: 95389d518dd4
schedule: */15 * * * *
mode: no_agent=true
deliver: local
script: forgerouter_scan.sh
profile: athos
```

## Admin rescan and auth

Read-only admin endpoints are public (they never expose secret values):

```bash
curl http://127.0.0.1:2100/admin/providers/health
curl http://127.0.0.1:2100/admin/routes/recent
curl http://127.0.0.1:2100/admin/providers/readiness
curl http://127.0.0.1:2100/admin/providers/registry
```

State-changing endpoints are protected once at least one agent is registered. Use any registered agent's API key (its AGENTE_API_KEY, shown on the Agents page) as the bearer token:

```bash
curl -H "Authorization: Bearer <agent api key>" -X POST http://127.0.0.1:2100/admin/providers/rescan

# create/update a provider and its models
curl -H "Authorization: Bearer <agent api key>" -H 'Content-Type: application/json' \
  -X PUT http://127.0.0.1:2100/admin/providers/groq \
  -d '{"name":"groq","tier":1,"base_url":"https://api.groq.com/openai/v1","api_key_env":"GROQ_API_KEY","enabled":true,"models":[{"id":"groq/llama-3.1-8b-instant","provider_model":"llama-3.1-8b-instant","capabilities":["text","tool_call"],"enabled":true}]}'

# delete a provider (cascades to its models)
curl -H "Authorization: Bearer <agent api key>" -X DELETE http://127.0.0.1:2100/admin/providers/groq
```

The dashboard loads provider data without a token. The token field (stored in browser localStorage) is needed for the `Run scan`, `Add provider`, edit and delete actions.

## Provider registry source of truth

The provider registry lives in PostgreSQL (`ai_router.providers` + `ai_router.models`) and is managed through the dashboard or the CRUD endpoints above. `config/providers.yaml` is only a fallback used when the database is unreachable or empty. Migration `db/004_provider_api_key_env.sql` added the `api_key_env` column to `ai_router.providers`.

## Runtime fallback

`/v1/chat/completions` now iterates through all healthy candidates for the required capability. If one provider returns HTTP >= 400 or raises during execution, ForgeRouter records the route event and tries the next healthy candidate before returning `all_providers_failed`.

## Expanded provider registry

Configured providers/models:

- `local/qwen2.5:1.5b` — healthy local fallback, text + tool_call
- `local/llama3.2:1b` — healthy local fallback, text
- `local/qwen2.5:0.5b` — healthy local fallback, text
- `groq/llama-3.1-8b-instant` — requires `GROQ_API_KEY`
- `openrouter/meta-llama/llama-3.2-3b-instruct:free` — requires `OPENROUTER_API_KEY`
- `openrouter/qwen/qwen-2.5-7b-instruct:free` — requires `OPENROUTER_API_KEY`
- `mistral/mistral-small-latest` — requires `MISTRAL_API_KEY`

Remote providers are expected to remain `unhealthy` with HTTP 401 until API keys are present in `.env`.

Runtime provider failures automatically persist an unhealthy health result, so subsequent routing avoids failed providers after the health override is refreshed from DB.

## Provider readiness endpoint

Admin endpoint that reports whether required API key environment variables are present without exposing secret values:

```bash
ADMIN_TOKEN="your_admin_token_here"
curl -H "Authorization: Bearer ${ADMIN_TOKEN}" http://127.0.0.1:2100/admin/providers/readiness
```

Fields:
- `api_key_env`: environment variable name only
- `api_key_required`: whether the provider requires a key
- `api_key_configured`: boolean only; never returns the secret

## Local production compose

A local runtime compose is available at:

```text
/root/.hermes/forgerouter/docker-compose.local.yml
```

Run:

```bash
cd /root/.hermes/forgerouter
docker compose -f docker-compose.local.yml up -d --build
```

This uses `network_mode: host` because local Ollama currently listens on `127.0.0.1:11434`. PostgreSQL remains Foundation-managed.
