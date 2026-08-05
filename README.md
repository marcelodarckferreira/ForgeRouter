<p align="center">
  <img alt="ForgeRouter" src="assets/logo.svg" width="420">
</p>

<p align="center">
  A self-hosted LLM gateway that routes chat completions and embeddings across multiple providers with health-based selection, automatic fallback, and demand-aware model routing — with an OpenAI-compatible API, an Anthropic Messages API translator, and an OpenAI Responses API translator all sharing one routing pipeline and streaming incrementally, end to end.
</p>

<p align="center">
  <img alt="License" src="https://img.shields.io/badge/license-MPL--2.0-orange">
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="FastAPI" src="https://img.shields.io/badge/framework-FastAPI-009688">
</p>

---

## What is ForgeRouter?

ForgeRouter sits in front of a pool of LLM providers — local models via Ollama, API-key providers (Groq, OpenRouter, Mistral, NVIDIA, Cloudflare, Cohere, Gemini Studio, GitHub Models, and more), and OAuth/subscription-based coding plans (Claude Code, Codex, Antigravity, DeepSeek, Z.ai) — and exposes them as one gateway. Point any OpenAI-compatible client, Claude Code, or the Codex CLI at it and it handles provider selection, health checks, and failover for you, so a single provider outage or a free-tier rate limit never breaks a request.

It speaks three client protocols against the same routing/fallback pipeline, plus a dedicated embeddings endpoint:

- **`/v1/chat/completions`** and **`/v1/models`** — OpenAI-compatible, including streaming (SSE).
- **`/v1/messages`** — Anthropic Messages API, for Claude Code. Streaming is real and incremental, translated chunk-by-chunk from the live provider response as it arrives — not a complete answer replayed as a synthesized SSE burst.
- **`/v1/responses`** — OpenAI Responses API, for the Codex CLI (required since Codex dropped Chat Completions support in v0.138). Same real incremental streaming as `/v1/messages`.
- **`/v1/embeddings`** — OpenAI-compatible, through the same health-based candidate selection and fallback as chat completions.

It ships with a built-in admin dashboard for managing providers, agents, routing, and usage — no separate service required.

## Features

- **Three client protocols, one router** — OpenAI Chat Completions, Anthropic Messages, and OpenAI Responses all translate down to the same request and share the same candidate selection, fallback, and health logic. All three stream incrementally from the live provider response — text and tool-call argument deltas arrive as the provider sends them, not a synthesized burst replayed after the fact.
- **Multi-provider routing** — mix local (Ollama) and remote providers (API-key or OAuth/subscription-based) in one pool, tiered by priority.
- **Health-based selection with automatic fallback** — candidates are tried in order; a failing, rate-limited, or unhealthy provider is skipped in favor of the next healthy one. A specific `model` in the request is a *preference*, not an exclusive filter — the rest of the healthy pool stays available as fallback.
- **Demand routing** — virtual models (`forgerouter/auto`, `simple`, `standard`, `complex`, `reasoning`, `vision`, `audio`, `code`) classify each request from its content (image or audio parts, code fences/hints, reasoning language, prompt size) and route it through an ordered chain of concrete models, so cheap requests don't burn a premium model's quota and vice versa.
- **In-process routing intelligence** — a per-provider circuit breaker (repeated failures open it temporarily), sticky routing (an agent's last-successful model for a given demand sticks around briefly to preserve provider prompt caches), and a dynamic score blending static model strength with recent success rate/latency.
- **Provider health scanner with startup & background watchdog** — periodically sends real chat completions to each configured model and detects *silent* failures too (HTTP 200 with empty content, quota/billing/auth error text in the body), not just connection errors. A full scan runs the moment the service boots, and a background check every 60s triggers an automatic rescan (rate-limited to once per 5 minutes) whenever the healthy pool drops below a minimum — surfaced via `/health` and a dashboard banner, so a fresh deploy or a flaky connection is never silently unreported.
- **Context compaction (lossless)** — strips incidental whitespace/formatting from outgoing messages before they hit the provider; no semantic content is ever removed. Before/after token counts are tracked per request.
- **Context truncation (lossy, opt-in)** — a safety valve for a runaway conversation history: once a request's estimated tokens cross a configurable percentage of the *selected model's actual context window*, the oldest turns are summarized by a cheap model (preserving names, decisions, numbers) and spliced in as a condensed note, rather than blowing past the model's real limit. Off by default; falls back to a plain mechanical drop if the summarization call fails.
- **Per-agent API keys and model controls** — issue a distinct API key per connected client/agent, restrict it to a subset of models or capability groups, set a monthly reference-cost budget, and classify it as a real conversational agent vs. an internal service consumer.
- **Reference cost estimation** — since ForgeRouter is built around free-tier routing, real billed cost is almost always zero; it estimates what a request *would* have cost at public commercial rates for an equivalent model, purely as an opportunity-cost figure.
- **Audit visibility without storing conversations** — ForgeRouter does not persist message bodies by design. The one bounded exception is a ~100-character preview of the last user message per request, kept for auditing what an agent is actually spending its quota on.
- **Admin dashboard** — a React/TypeScript UI for managing providers, agents, routing/demand chains, pricing, and usage, served directly by the API — including a tri-state model status breakdown (healthy / disabled / unresponsive) so an intentionally-disabled model never reads as an outage.
- **Database-backed with YAML fallback** — the provider registry lives in PostgreSQL; a bundled YAML config is used automatically if the database is unreachable or empty, so routing never goes down with it.

## Architecture

```
Client (OpenAI SDK, Claude Code, Codex CLI, curl, ...)
        │
        ▼
 POST /v1/chat/completions  ·  /v1/messages  ·  /v1/responses
        │                         (translated to a Chat Completions
        │                          request, then translated back)
        ▼
 Load provider registry (PostgreSQL, YAML fallback)
        │
        ▼
 Classify demand (auto/simple/standard/complex/reasoning/vision/audio/code)
        │
        ▼
 Infer capability → filter healthy, enabled candidates → sort by demand chain, tier, dynamic score
        │
        ▼
 Context compaction (lossless) → context truncation (opt-in, lossy) → try candidates in order
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

# Build the image — bakes the current commit into the image (readable at
# runtime via GET /health) and tags it forgerouter:<VERSION> + forgerouter:latest.
./scripts/build.sh

# Apply the database schema (run each numbered file in db/ in order, against
# a role with permission to create the ai_router schema and its tables)
for f in db/*.sql; do
  psql "$DATABASE_URL" -f "$f"
done

# Start the service
docker compose up -d
```

Check that it's up:

```bash
curl http://127.0.0.1:2100/health
# {"status":"ok","version":"0.1.0","git_sha":"<commit>"}
```

The dashboard is served at `http://127.0.0.1:2100/` — the default login is `admin` / `admin`, and you'll be prompted to change it on first sign-in.

> **Local Ollama note:** if you run Ollama on the host, use `docker-compose.local.yml` (host networking) instead, so the container can reach `127.0.0.1:11434`:
> ```bash
> docker compose -f docker-compose.local.yml up -d --build
> ```

### Configuration

ForgeRouter's own behavior is tuned through a small set of environment variables; the provider/model/agent registry itself lives in PostgreSQL and is managed at runtime through the dashboard or the `/admin/*` endpoints — `.env` only needs credentials, not the registry.

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `DATABASE_CONNECT_TIMEOUT` | Connection timeout in seconds (default `5`) |
| `<PROVIDER>_API_KEY` (e.g. `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY`) | Per-provider API keys — only required for the providers you enable, matching each provider's `api_key_env` in `config/providers.yaml` |
| `FORGEHUB_SSO_SECRET` | Optional shared secret for trusted SSO from a companion app (server-to-server) |
| `AUTO_INCLUDE_MIN_HEALTHY` | Minimum healthy candidates before runtime-degraded models (e.g. rate-limited) re-enter routing as last-resort reserves (default `3`) |
| `BREAKER_THRESHOLD` | Consecutive provider failures before the in-process circuit breaker opens (default `4`) |
| `BREAKER_COOLDOWN_SECONDS` | How long an open breaker stays open before a half-open probe (default `120`) |
| `STICKY_TTL_SECONDS` | How long an agent's last-successful model for a demand class stays "sticky" (default `600`) |

Everything else — which providers are enabled, which models they expose, demand-routing chains, context compaction/truncation, agent keys and budgets, pricing sync — is configured live through the dashboard and persisted in PostgreSQL, not through environment variables or a redeploy.

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

Ask for a specific demand class instead of automatic classification:

```bash
curl http://127.0.0.1:2100/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <agent-api-key>" \
  -d '{"model": "forgerouter/code", "messages": [{"role": "user", "content": "Write a bubble sort in Rust"}]}'
```

List available models:

```bash
curl http://127.0.0.1:2100/v1/models
```

Request an embedding:

```bash
curl http://127.0.0.1:2100/v1/embeddings \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <agent-api-key>" \
  -d '{"model": "auto", "input": "Hello, world!"}'
```

Any OpenAI-compatible SDK works out of the box by pointing `base_url` at `http://127.0.0.1:2100/v1`. Claude Code and the Codex CLI can point at `http://127.0.0.1:2100` directly (`/v1/messages` and `/v1/responses` respectively) using an agent API key as the bearer token.

## Development

```bash
# Run the full test suite
docker compose run --rm forgerouter pytest -q

# Run a single test file / test
docker compose run --rm forgerouter pytest tests/test_chat_fallback.py -q
docker compose run --rm forgerouter pytest tests/test_chat_fallback.py::test_chat_falls_back_to_next_candidate -q

# Rebuild the dashboard after frontend changes, then rebuild the image
cd frontend && npm install && npm run build && cd .. && ./scripts/build.sh
```

Frontend and backend tests use FastAPI's `TestClient` and monkeypatched registry/persistence functions — no live database or providers are required to run the suite.

## License

[Mozilla Public License 2.0](LICENSE)
