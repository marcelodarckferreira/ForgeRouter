# HERMES_AI_PROXY_ROUTER_PRD_v2

## Objective

Build the Hermes AI Provider Orchestrator: a proxy/router with one OpenAI-compatible API for Hermes, capable of routing across:

1. CLI-authenticated paid providers.
2. Free remote providers.
3. Local models.

## Provider Layers

### Layer 1 — CLI Auth Paid Providers

Supported:

- OpenAI Codex CLI
- Claude Code
- Gemini CLI

The system must not scrape or extract private session tokens. CLI providers must run as isolated subprocess adapters.

Official behavior checked:

- Codex CLI supports ChatGPT sign-in and API key auth. Codex CLI can reuse cached local login. 
- Claude Code supports Claude.ai, Team/Enterprise, Console and cloud provider auth.
- Gemini CLI supports Google OAuth login and API key/Vertex modes.

## Layer 2 — Free Remote Providers

Initial providers:

- NVIDIA
- SambaNova
- Z.ai
- MiniMax
- OpenRouter
- Groq
- Cerebras
- Mistral

The system must continuously validate free models because availability, quota and model lists change frequently.

## Layer 3 — Local Models

Supported backends:

- Ollama
- llama.cpp
- vLLM
- LM Studio, optional

Local fallback is mandatory.

## Capabilities

Every model must be classified by:

- text
- code
- reasoning
- tool_call
- vision
- embedding
- audio

## Success Criteria

MVP is complete when:

1. Hermes calls one `/v1/chat/completions` endpoint.
2. `model=auto` chooses a healthy model.
3. Free providers are scanned and ranked.
4. CLI providers are isolated and audited.
5. Local fallback works.
6. No secret is logged.
7. Routing decisions are persisted in PostgreSQL.
