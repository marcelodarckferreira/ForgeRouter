<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/logo-light.svg">
    <img alt="ForgeRouter" src="assets/logo-light.svg" width="420">
  </picture>
</p>

<p align="center">
  A self-hosted, OpenAI-compatible API gateway that routes chat completions across multiple LLM providers with health-based selection and automatic fallback.
</p>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-MPL--2.0-orange">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="FastAPI" src="https://img.shields.io/badge/framework-FastAPI-009688">
</p>

---

## What is ForgeRouter?

ForgeRouter exposes a single OpenAI-compatible API — `/v1/chat/completions` and `/v1/models` — and routes each request across a configurable pool of LLM providers (local models via Ollama, and remote providers such as Groq, OpenRouter, Mistral, or OAuth-based coding-plan subscriptions). Point any OpenAI-compatible client at it, and it handles provider selection, health checks, and failover for you.

It ships with a built-in admin dashboard for managing providers, agents, and usage — no separate service required.

## Features

- **OpenAI-compatible API** — drop-in `/v1/chat/completions` and `/v1/models`, including streaming (SSE) responses.
- **Multi-provider routing** — mix local (Ollama) and remote providers (API-key or OAuth/subscription-based) in one pool.
- **Health-based selection with automatic fallback** — candidates are tried in tier order; a failing or rate-limited provider is skipped in favor of the next healthy one, so a single provider outage never breaks a request.
- **Demand routing** — virtual models (`forgerouter/auto`, `simple`, `standard`, `complex`, `reasoning`, `vision`) classify each request and route it through an ordered chain of concrete models.
- **Provider health scanner** — periodically sends real chat completions to each configured model and detects silent failures (HTTP 200 with empty content, quota/billing errors, etc.), not just connection errors.
- **Per-agent API keys and model controls** — issue a distinct API key per connected client/agent, optionally restricting it to a subset of models, with usage attribution.
- **Context compaction** — lossless whitespace normalization of outgoing messages, with before/after token accounting.
- **Admin dashboard** — a React/TypeScript UI for managing providers, agents, viewing health, recent routes, and usage, served directly by the API.
- **Database-backed with YAML fallback** — the provider registry lives in PostgreSQL; a bundled YAML config is used automatically if the database is unreachable, so routing never goes down with it.

## Architecture

```
Client (OpenAI SDK, curl, etc.)
        │
        ▼
 POST /v1/chat/completions
        │
        ▼
 Load provider registry (PostgreSQL, YAML fallback)
        │
        ▼
 Infer capability (text / tool_call / vision) → filter healthy, enabled candidates
        │
        ▼
 Sort candidates by tier → try in order
        │
        ├─ success ──────────────► response streamed/returned to client
        │
        └─ failure ── record route event, mark unhealthy ── try next candidate
                                                                   │
                                                    all exhausted ─┴─► 502 all_providers_failed
```

Each provider has an `api_format` (`openai` or `anthropic`) describing its wire protocol; subscription-based providers (Claude Code, Codex, Antigravity, DeepSeek, Z.ai) go through dedicated plan handlers that manage OAuth tokens instead of static API keys.

## Getting started

### Prerequisites

- Docker and Docker Compose
- A PostgreSQL instance (or use the bundled compose service)
- Optional: [Ollama](https://ollama.com) running locally for local-model fallback

### Installation

```bash
git clone https://github.com/marcelodarckferreira/ForgeRouter.git
cd ForgeRouter

# Copy the example environment file and fill in your database and provider credentials
cp .env.example .env

# Build the image
docker compose build

# Apply the database schema (run each file in db/ in order against your PostgreSQL instance)
for f in db/*.sql; do
  psql "$DATABASE_URL" -f "$f"
done

# Start the service
docker compose up -d
```

Check that it's up:

```bash
curl http://127.0.0.1:2100/health
```

The dashboard is served at `http://127.0.0.1:2100/` — the default login is `admin` / `admin`, and you'll be prompted to change it on first sign-in.

> **Local Ollama note:** if you run Ollama on the host, use `docker-compose.local.yml` (host networking) instead, so the container can reach `127.0.0.1:11434`:
> ```bash
> docker compose -f docker-compose.local.yml up -d --build
> ```

### Configuration

Core environment variables (see `config/providers.yaml` and `db/002_seed_registry.sql` for the full provider list):

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `APP_HOST` / `APP_PORT` | Bind address (default `127.0.0.1:2100`) |
| `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`, ... | Per-provider API keys, only required for the providers you enable |
| `ENABLE_PAID_FALLBACK` | Whether paid providers may be used as a fallback |
| `LOG_PROMPTS` | Whether prompt content is logged (defaults to `false`) |

Providers and models are managed at runtime through the dashboard or the `/admin/providers` CRUD endpoints — the `.env` file only needs to hold credentials, not the registry itself.

## Usage

```bash
curl http://127.0.0.1:2100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <agent-api-key>" \
  -d '{
    "model": "forgerouter/auto",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

List available models:

```bash
curl http://127.0.0.1:2100/v1/models
```

Any OpenAI-compatible SDK works out of the box by pointing `base_url` at `http://127.0.0.1:2100/v1`.

## Development

```bash
# Run the full test suite
docker compose run --rm forgerouter pytest -q

# Run a single test file
docker compose run --rm forgerouter pytest tests/test_chat_fallback.py -q

# Rebuild the dashboard after frontend changes
cd frontend && npm install && npm run build
```

## License

[Mozilla Public License 2.0](LICENSE)
