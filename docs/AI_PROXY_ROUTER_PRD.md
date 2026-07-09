# AI Proxy Router PRD

**Version:** 0.1.0  
**Status:** Draft / Planning  
**Created:** 2026-06-09T18:12:40-03:00  
**Owner:** Athos  
**Ticket:** PENDING_KANBOARD  
**Related:** `FOUNDATION.md`, `PIR.md`, `llm_governance.yaml`  

---

## 1. Objective

Build a simple and functional AI proxy router for the Hermes ecosystem, inspired by Manifest, but optimized for Marcelo's operational requirements:

1. Expose one OpenAI-compatible endpoint for all Hermes agents.
2. Validate all configured providers and their free-tier modules/models.
3. Route requests only to models that are actually usable.
4. Treat "working" as real operational usability, not merely returning any text.
5. Preserve local LLM fallback as mandatory last-resort availability.
6. Keep the implementation small, observable, auditable, and easy to deploy.

This PRD is planning only. No development is authorized by this document alone.

---

## 2. Background

The Foundation currently records Manifest as the active model-routing layer for Hermes profiles:

```yaml
model:
  provider: custom
  base_url: http://localhost:2099/v1
  api_key: <manifest-api-key>
  default: auto
```

The historical Provider Intelligence Router (PIR) is deactivated and preserved for audit/rollback. PIR already provides useful concepts that should be reused in the new router design:

- provider tiering;
- provider/model registry;
- provider health history;
- content-aware health validation;
- fallback chain;
- PostgreSQL-backed observability;
- local model last-resort tier.

Manifest provides the useful product pattern:

- one proxy endpoint;
- provider abstraction;
- automatic fallback;
- routing by request complexity/cost;
- local and remote providers;
- dashboard/observability.

The new router should start smaller than Manifest: first provider validation + reliable OpenAI-compatible routing, then scoring/cost/dashboard later.

---

## 3. Problem Statement

Current risk: the ecosystem can point to an AI router, but provider/model health and free-tier usability need deterministic validation.

A provider should not be considered healthy only because it returns HTTP 200 or produces generic text. For Hermes agents, a provider/model is working only if it can satisfy the module capability expected from it.

Examples:

- A text-only model can be valid for summarization but invalid for tool-call agent execution.
- A model that returns empty content is not working.
- A model that returns quota/subscription/billing text inside HTTP 200 is not working.
- A provider with an expired free tier must be marked unavailable until reset.
- Local models must be available as guaranteed fallback when remote providers fail.

---

## 4. Product Scope

### 4.1 In scope for MVP

- OpenAI-compatible `/v1/chat/completions` endpoint.
- OpenAI-compatible `/v1/models` endpoint.
- Health endpoint: `/health`.
- Provider registry loaded from YAML and/or PostgreSQL.
- Validation of provider auth, model availability, content quality, and capability modules.
- Free-tier module validation for all configured free providers.
- Routing by explicit model, capability, and fallback tier.
- `model: auto` support.
- Local fallback support for Ollama and llama.cpp.
- Structured request/route/health logs.
- Simple CLI scanner for provider validation.
- Safe default: never route to a provider marked unhealthy for the required capability.

### 4.2 Out of scope for MVP

- Full web dashboard.
- Billing and cost tracking.
- Multi-user SaaS controls.
- OAuth/subscription reuse flows.
- Prompt caching.
- Embeddings/images/audio endpoints.
- Fine-grained semantic complexity routing beyond simple heuristics.
- Automatic modification of Hermes profile config files.

---

## 5. Users and Stakeholders

| Role | Need |
|---|---|
| Marcelo | Stable, low-friction, low-cost AI routing with clear provider health. |
| Athos | Operational control, planning, validation, and incident response. |
| Hermes runtime agents | Single compatible endpoint with reliable fallback. |
| Daedalus | Simple codebase, testable provider adapters, maintainable API. |
| Hephaestus | Deployable service with health checks, logs, and rollback. |
| Aegis | No secret leakage, safe provider handling, auditable operations. |
| Mnemosyne/Atlas | Reliable model availability for knowledge/memory workflows. |

---

## 6. Success Criteria

MVP is successful when:

1. Hermes can call the router through one OpenAI-compatible endpoint.
2. `model=auto` routes to a healthy provider/model.
3. Every enabled free-tier provider/model has a current validation status.
4. Capability checks distinguish at least: `text`, `tool_call`, `code`, `reasoning`, `vision`.
5. A model that returns HTTP 200 but empty/blocked/quota/subscription content is marked unhealthy.
6. Local fallback works when all remote free providers fail.
7. Route decision is logged with provider, model, reason, latency, and fallback path.
8. No secrets are printed in logs or API responses.
9. Service can be deployed locally and verified with curl.

---

## 7. Provider Validation Definition

### 7.1 Working provider/model

A provider/model is `working` only if all required checks pass:

1. Transport check: endpoint reachable within timeout.
2. Auth check: no 401/403 caused by invalid key or blocked plan.
3. Model check: target model exists and accepts request format.
4. Response check: non-empty assistant content or valid tool-call structure.
5. Silent failure check: response body does not contain quota/billing/subscription/blocking errors.
6. Capability check: model passes the expected module test.

### 7.2 Capability modules

| Capability | Validation method | MVP requirement |
|---|---|---|
| text | Ask deterministic short prompt. Require non-empty coherent answer. | Required for all models. |
| tool_call | Send one function schema and require valid tool call arguments. | Required for primary agent models. |
| code | Ask for a tiny function or bug fix and validate shape, not full benchmark. | Required for coding lane models. |
| reasoning | Ask a simple multi-step problem and require final answer marker. | Optional classification. |
| vision | Send small image payload or known image URL if provider supports multimodal. | Optional for vision models. |

### 7.3 Silent failure patterns

Mark unhealthy if response contains patterns such as:

- `unauthorized`
- `invalid api key`
- `insufficient quota`
- `billing`
- `balance`
- `subscription`
- `limit exceeded`
- `rate limit`
- `model not found`
- empty `choices`
- empty `message.content` with no valid `tool_calls`

---

## 8. Provider Inventory Baseline

Initial inventory should be seeded from Foundation/PIR data.

### 8.1 Tiers

| Tier | Name | Strategy |
|---|---|---|
| 1 | primary/free accelerated | NVIDIA NIM and equivalent fast reliable providers. |
| 2 | free remote | Free-tier providers: Mistral, SambaNova, Z.ai, OpenRouter, Groq, Cerebras, MiniMax, OpenCode, Cloudflare, Ollama Cloud where available. |
| 3 | paid emergency | Paid provider only when explicitly enabled by policy. |
| 4 | local fallback | Ollama local and llama.cpp. Mandatory no-internet fallback. |

### 8.2 Known configured providers from current PIR registry

Enabled/known candidates observed in Foundation/PIR:

- NVIDIA NIM: `nvidia/nemotron-3-super-120b-a12b`, `nvidia/llama-3.3-nemotron-super-49b-v1`, `meta/llama-3.3-70b-instruct`, `meta/llama-3.1-70b-instruct`.
- Mistral: `mistral-small-latest`.
- SambaNova: `Meta-Llama-3.3-70B-Instruct`.
- Z.ai: `glm-5.1`, `glm-5`, `glm-4.7`.
- Ollama Cloud: `gemma4:31b`.
- Ollama Local: `qwen2.5:1.5b`.
- llama.cpp: `MiniCPM-V-4_6-Q4_K_M.gguf`, `llamacpp/local`.
- Disabled but historically tracked: OpenRouter, Groq, Cerebras, MiniMax, OpenCode Zen, Cloudflare, paid OpenAI-compatible fallback.

MVP must validate disabled/free providers too, but must not enable them for routing unless validation and policy allow it.

---

## 9. Functional Requirements

### FR-001: OpenAI-compatible chat endpoint

The router must expose:

```text
POST /v1/chat/completions
```

Minimum accepted request fields:

- `model`
- `messages`
- `tools`
- `tool_choice`
- `temperature`
- `max_tokens`
- `stream` (MVP may reject with clear error if unsupported)

### FR-002: Auto model routing

When request uses `model: auto`, router selects the cheapest/lowest-tier healthy model that satisfies required capability.

Capability inference:

- If request includes `tools`, require `tool_call`.
- If prompt includes code blocks or coding intent, prefer `code` capability.
- If message includes image content, require `vision`.
- Otherwise require `text`.

### FR-003: Explicit model routing

When request uses a known explicit model, route to that model only if current health is valid for the inferred capability.

If unavailable, return structured error unless `allow_fallback=true` header/config is enabled.

### FR-004: Fallback chain

If selected provider fails during execution:

1. Retry same provider once only for transient network/5xx errors.
2. Try next healthy model with same capability in same tier.
3. Escalate through configured tiers.
4. End at local fallback.
5. Return final error only after all eligible models fail.

### FR-005: Provider scanner

Provide CLI:

```bash
ai-router providers scan --all
ai-router providers scan --tier free
ai-router providers scan --provider mistral
ai-router providers list --status
```

Scanner must persist:

- status;
- HTTP code;
- latency;
- capabilities passed/failed;
- error category;
- timestamp;
- raw response excerpt sanitized.

### FR-006: Health endpoints

Expose:

```text
GET /health
GET /v1/models
GET /admin/providers/health
```

`/health` returns router health.  
`/v1/models` returns only routable healthy models by default.  
`/admin/providers/health` returns detailed provider status with auth required.

### FR-007: Observability

Every request should log:

- request id;
- selected provider/model;
- fallback attempts;
- capability required;
- latency;
- token usage if returned by provider;
- error category;
- final status.

### FR-008: Secret handling

Secrets must be loaded only from environment or local secret files, never hardcoded.

Logs must redact:

- API keys;
- bearer tokens;
- Authorization headers;
- database URLs with passwords;
- user prompts if privacy mode is enabled.

---

## 10. Non-functional Requirements

| Area | Requirement |
|---|---|
| Simplicity | Small service, minimal moving parts, no dashboard in MVP. |
| Runtime | Python FastAPI or Node/Nest acceptable; prefer FastAPI for fast MVP and easy validation scripts. |
| Compatibility | Must behave as OpenAI-compatible provider for Hermes `custom` config. |
| Storage | PostgreSQL preferred if Foundation DB is available; SQLite acceptable for standalone dev mode. |
| Deployment | Docker Compose local service, default localhost binding. |
| Security | Admin endpoints protected by API key. No secret logging. |
| Reliability | Router must keep working if optional DB logging fails; route memory can degrade to in-process cache. |
| Performance | Add less than 200ms overhead excluding provider latency. |
| Maintainability | Provider adapters isolated by provider/API format. |

---

## 11. Architecture Proposal

### 11.1 Components

```text
Hermes Agent
  -> OpenAI-compatible Router API
      -> Request classifier
      -> Provider registry
      -> Health/capability cache
      -> Routing policy engine
      -> Provider adapters
          -> NVIDIA / Mistral / SambaNova / Z.ai / OpenRouter / Groq / Ollama / llama.cpp / Custom
      -> Logs + health store
```

### 11.2 Suggested service layout

```text
/root/work/ecosystem/services/ai-proxy-router/
  app/
    main.py
    config.py
    schemas.py
    routing/policy.py
    routing/classifier.py
    providers/base.py
    providers/openai_compatible.py
    providers/ollama.py
    validation/scanner.py
    validation/capabilities.py
    storage/repository.py
    security/redaction.py
  config/
    providers.yaml
  tests/
    test_routing_policy.py
    test_capability_validation.py
    test_openai_compat.py
  docker-compose.yml
  Dockerfile
  README.md
```

### 11.3 Storage tables

If using PostgreSQL:

```sql
ai_router_providers
ai_router_models
ai_router_health
ai_router_routes
ai_router_requests
```

These can be new tables to avoid mutating historical PIR tables. PIR can remain read-only input/reference.

---

## 12. Routing Policy MVP

Default order:

1. Healthy Tier 1 model matching capability.
2. Healthy Tier 2 free model matching capability.
3. Paid Tier 3 only if `ENABLE_PAID_FALLBACK=true`.
4. Local Tier 4 model matching capability.

Hard rules:

- Never use a provider without valid health for the required capability.
- Never use paid fallback unless explicitly enabled.
- Never remove local fallback from the chain.
- Never mutate Hermes profile config automatically.
- Never mark provider healthy from HTTP code alone.

---

## 13. API Contract Draft

### 13.1 Chat completions

```http
POST /v1/chat/completions
Authorization: Bearer <router-api-key>
Content-Type: application/json
```

Request:

```json
{
  "model": "auto",
  "messages": [{"role": "user", "content": "Say OK"}],
  "temperature": 0
}
```

Response: OpenAI-compatible response from selected provider, with optional internal headers:

```text
x-ai-router-request-id: <uuid>
x-ai-router-provider: mistral
x-ai-router-model: mistral-small-latest
x-ai-router-fallback-count: 0
```

### 13.2 Provider health

```http
GET /admin/providers/health
Authorization: Bearer <admin-api-key>
```

Response:

```json
{
  "providers": [
    {
      "provider": "mistral",
      "model": "mistral-small-latest",
      "tier": "free",
      "status": "healthy",
      "capabilities": {"text": true, "tool_call": true},
      "latency_ms": 650,
      "checked_at": "2026-06-09T18:12:40-03:00"
    }
  ]
}
```

---

## 14. Validation Plan

### 14.1 Unit tests

- Capability inference from request.
- Silent failure detection.
- Fallback order.
- Provider registry parsing.
- Secret redaction.

### 14.2 Integration tests

- Fake OpenAI-compatible provider returning success.
- Fake provider returning HTTP 200 with quota error in body.
- Fake provider returning empty content.
- Fake provider returning valid tool call.
- Router fallback from failed primary to local fake provider.

### 14.3 Live validation

Run only after credentials are available:

```bash
ai-router providers scan --all
curl -s http://localhost:<port>/health
curl -s http://localhost:<port>/v1/models -H "Authorization: Bearer $AI_ROUTER_API_KEY"
curl -s http://localhost:<port>/v1/chat/completions \
  -H "Authorization: Bearer $AI_ROUTER_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"auto","messages":[{"role":"user","content":"Reply only OK"}],"temperature":0}'
```

Expected evidence:

- scanner report showing provider statuses;
- `/health` returns OK;
- `/v1/models` returns healthy models only;
- chat completion returns `OK` through selected provider;
- logs show route decision.

---

## 15. Implementation Plan

### Phase 0 — Approval and ticketing

- Restore/create Kanboard task when Kanboard is reachable.
- Confirm MVP scope and service path.
- Confirm whether replacing Manifest is the target or whether this is a parallel candidate first.

### Phase 1 — Skeleton

- Create service directory.
- Add FastAPI app.
- Add `/health`, `/v1/models`, `/v1/chat/completions` skeleton.
- Add config loader for `providers.yaml`.
- Add tests for schemas and endpoints.

### Phase 2 — Provider adapters

- Implement generic OpenAI-compatible adapter.
- Implement local Ollama/llama.cpp compatibility via OpenAI-compatible endpoints.
- Add timeout, retry, and error normalization.

### Phase 3 — Validation scanner

- Implement text validation.
- Implement tool-call validation.
- Implement silent failure detection.
- Persist health results.
- Generate CLI status table.

### Phase 4 — Routing policy

- Implement capability inference.
- Implement tier/fallback selection.
- Implement execution fallback on provider failure.
- Add route decision headers/logs.

### Phase 5 — Deployment candidate

- Add Dockerfile and docker-compose.
- Bind to localhost by default.
- Add `.env.example` without secrets.
- Validate with fake providers and at least one real local provider.

### Phase 6 — Controlled integration

- Run side-by-side with Manifest on a different port.
- Point one non-critical Hermes profile/session to the new router.
- Validate Telegram -> Hermes -> Router -> Model path.
- Only after evidence, prepare replacement plan for Manifest if desired.

---

## 16. Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Provider returns HTTP 200 with unusable response | False healthy status | Content-aware checks and capability validation. |
| Free tiers rate-limit during scan | Provider marked unavailable | Store error category and next retry window. |
| Paid model used accidentally | Cost risk | Paid fallback disabled by default. Requires env flag. |
| Secret leakage in logs | Security incident | Central redaction before logging. Tests for redaction. |
| Router becomes single point of failure | Agents blocked | Local fallback, health endpoint, simple rollback to Manifest. |
| Overbuilding dashboard | Delivery delay | No dashboard in MVP. CLI and JSON health only. |
| Mutating profile configs automatically | Operational instability | Manual integration only after approval. |

---

## 17. Open Decisions

1. Service name: `ai-proxy-router`, `hermes-router`, or `mnemon-router`?
2. Preferred implementation stack: FastAPI/Python vs Node/TypeScript?
3. Should the MVP read existing PIR PostgreSQL tables as seed data, or start from `providers.yaml` only?
4. Should Manifest remain active while the new router runs side-by-side?
5. Which providers are mandatory for first live scan?
6. Should admin endpoints be exposed only on localhost or protected behind gateway auth?

Recommendation:

- Use FastAPI/Python.
- Start with `providers.yaml` seeded from PIR, then optionally mirror health into PostgreSQL.
- Run side-by-side with Manifest first.
- Do not switch Hermes profiles until live validation passes.

---

## 18. Definition of Ready for Development

Development may start when:

- Kanboard ticket exists.
- MVP scope is approved.
- service path is approved.
- implementation stack is approved.
- provider list for first scan is approved.
- decision is made: side-by-side candidate vs direct Manifest replacement.

---

## 19. Definition of Done for MVP

MVP is done only when validated evidence exists:

- file tree exists under approved service path;
- tests pass;
- docker compose starts service;
- `/health` returns OK;
- `/v1/models` returns healthy models only;
- scanner validates provider statuses;
- at least one remote free provider and one local provider are tested;
- chat completion through `model=auto` works;
- fallback is demonstrated using a forced failing provider;
- no secrets appear in logs;
- Kanboard task has evidence comment.

---

## 20. Current Evidence Collected During PRD Creation

- `FOUNDATION.md` confirms Manifest is active model-routing layer at `http://localhost:2099/v1`.
- `PIR.md` confirms PIR is deactivated and preserved for rollback/audit.
- Local Manifest endpoint is reachable and returns auth error without bearer token, proving service is up.
- Kanboard healthcheck returned `http_unreachable url=http://localhost:8081/ timeout_s=5`; therefore final Kanboard ticket is pending.
- PIR PostgreSQL provider inventory was readable and contains 24 provider/model rows across nvidia, free, paid, and local tiers.

---

## 21. Recommended Next Step

Create implementation plan after Marcelo approves:

1. Service name and path.
2. Stack: FastAPI/Python recommended.
3. Side-by-side with Manifest first.
4. First provider scan list:
   - Mistral;
   - SambaNova;
   - Z.ai;
   - NVIDIA;
   - Ollama local;
   - llama.cpp;
   - disabled free providers as diagnostics only.
