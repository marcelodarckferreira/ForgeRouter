# HERMES_AI_PROXY_ROUTER_SPEC_v1

## Architecture

Hermes -> AI Proxy Router -> Routing Engine -> Provider Adapter

Provider adapters:

1. CLI Provider Adapter
2. OpenAI-Compatible Provider Adapter
3. Local Provider Adapter

## Runtime Stack

Recommended:

- Python 3.12
- FastAPI
- PostgreSQL
- SQLAlchemy 2
- APScheduler
- Redis optional

## API

### POST /v1/chat/completions

Accepts OpenAI-compatible request.

Required fields:

- model
- messages

Optional:

- tools
- tool_choice
- temperature
- max_tokens
- stream

### GET /v1/models

Returns only healthy routable models by default.

### GET /health

Returns service status.

### GET /admin/providers/health

Requires admin auth.

## Routing Flow

1. Receive request.
2. Infer capability.
3. Filter healthy models.
4. Rank candidates.
5. Execute selected adapter.
6. Fallback on failure.
7. Log route decision.

## Capability Inference

Rules:

- tools present -> tool_call
- image content present -> vision
- code blocks or coding intent -> code
- multi-step reasoning prompt -> reasoning
- default -> text

## Ranking Formula

```text
score =
quality_score * 0.30 +
health_score * 0.25 +
capability_score * 0.20 +
latency_score * 0.10 +
cost_score * 0.10 +
hardware_fit_score * 0.05
