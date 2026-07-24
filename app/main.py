from __future__ import annotations

from typing import Any, Iterable, Iterator
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from pydantic import BaseModel, Field

from app.demand import DEMAND_INFO, DEMANDS, VIRTUAL_MODELS, default_chain, messages_have_images, resolve_demand
from app.normalize import count_tokens, normalize_messages
from app.routing_state import (
    breaker_open,
    model_performance_cached,
    record_provider_failure,
    record_provider_success,
    record_sticky,
    sticky_model,
)
from app.registry import load_registry, load_registry_with_db_health, provider_readiness
from app.providers.openai_compatible import build_chat_payload, chat_completion
from app.deploy_config import apply_agent_deploy_config
from app.validation.health import detect_silent_failure
from app.storage import (
    agent_allowed_models,
    archive_old_route_events,
    authenticate_user,
    backfill_reference_costs,
    change_credentials,
    context_compaction_enabled,
    count_active_admins,
    create_agent,
    create_session,
    create_user,
    delete_agent,
    delete_profile,
    delete_provider,
    delete_session,
    delete_user,
    duplicate_agent,
    ensure_default_user,
    find_agent_by_key,
    agent_month_spend,
    get_agent_budget,
    set_agent_budget,
    first_user,
    list_profiles,
    list_users,
    save_profile,
    update_user,
    user_permissions,
    get_agent_api_key,
    get_agent_deploy_config,
    set_agent_deploy_config,
    get_demand_routes,
    get_setting,
    has_any_agent,
    set_demand_routes,
    set_context_compaction_enabled,
    set_setting,
    latest_provider_health_rows,
    list_agents_with_usage,
    mark_runtime_failure_unhealthy,
    persist_health_results,
    persist_route_event,
    recent_route_events,
    rename_agent,
    rotate_agent_key,
    runtime_degraded_models,
    session_user,
    set_agent_description,
    set_agent_kind,
    set_agent_models,
    set_aux_tasks_agent,
    set_models_enabled_from_health,
    sync_agent_model_associations,
    upsert_provider,
)
from app.validation.scanner import build_scan_payload, scan_registry

app = FastAPI(title="ForgeRouter", version="0.1.0")


class ChatMessage(BaseModel):
    model_config = {"extra": "allow"}

    role: str
    content: Any = None
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[Any] | None = None


class ChatCompletionRequest(BaseModel):
    model: str = "auto"
    messages: list[ChatMessage] = Field(default_factory=list)
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False


class AnthropicMessagesRequest(BaseModel):
    model: str = "auto"
    messages: list[dict[str, Any]] = Field(default_factory=list)
    system: Any = None
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False


def infer_capability(request: ChatCompletionRequest, demand: str | None = None) -> str:
    # Images are a hard requirement (a non-vision model cannot read them at all),
    # so they take priority over tool_call — an agentic request that attaches both
    # tools and an image must still land on a vision-capable model.
    if messages_have_images(request.messages):
        return "vision"
    # Audio/code are catalog particularities too (default_chain gates them the
    # same way): an agentic request commonly attaches tools regardless of task
    # type, so without this a code/audio-capable model that lacks tool_call
    # support would be excluded from the initial candidate pool before
    # default_chain ever gets to apply its own capability filter.
    if demand in ("audio", "code"):
        return demand
    if request.tools:
        return "tool_call"
    return "text"


class ModelHealthPayload(BaseModel):
    status: str
    http_code: int | None = None
    latency_ms: int | None = None
    error: str | None = None


class ProviderModelPayload(BaseModel):
    id: str
    provider_model: str = ""
    capabilities: list[str] = Field(default_factory=lambda: ["text"])
    enabled: bool = True
    health: ModelHealthPayload | None = None  # discovery scan result, persisted on save


class ProviderPayload(BaseModel):
    name: str
    tier: int
    base_url: str
    api_key_env: str = ""
    api_key: str = ""  # write-only: empty means "keep the stored key"
    enabled: bool = True
    access_type: str = "api_key"  # subscription | api_key | local
    cost_type: str = "free"  # free | paid
    api_format: str = "openai"  # openai (/chat/completions) | anthropic (Messages API /v1/messages)
    auth_config: dict[str, Any] = Field(default_factory=dict)  # non-secret particularities (e.g. extra_headers)
    models: list[ProviderModelPayload] = Field(default_factory=list)


class DiscoverModelsPayload(BaseModel):
    provider_name: str = ""
    base_url: str = ""
    api_key: str = ""
    api_key_env: str = ""
    api_format: str = ""  # empty = stored provider's format, defaulting to openai
    scan: bool = True
    scan_timeout: float = 20.0



FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="assets")


@app.get("/")
def frontend_index():
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        # The JS/CSS assets are content-hashed; index.html must never be cached or the
        # browser keeps loading an old bundle after a deploy.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return {"service": "ForgeRouter", "dashboard": "not_built"}

def _read_version() -> str:
    try:
        return Path("VERSION").read_text(encoding="utf-8").strip()
    except Exception:
        return "unknown"


@app.get("/health")
def health():
    # version/git_sha identify exactly what code is running — compare against
    # `docker images`/`git rev-parse HEAD` to catch a stale image before it bites
    # (see CLAUDE.md: forgerouter:latest went stale for over a week undetected).
    return {"status": "ok", "version": _read_version(), "git_sha": os.environ.get("FORGEROUTER_GIT_SHA", "unknown")}


@app.get("/v1/models")
def models():
    registry = load_registry_with_db_health()
    virtual = [
        {
            "id": model_id,
            "object": "model",
            "owned_by": "forgerouter",
            "metadata": {"virtual": True, "description": DEMAND_INFO.get(model_id.split("/", 1)[1], "Routes by demand class automatically.")},
        }
        for model_id in VIRTUAL_MODELS
    ]
    return {"object": "list", "data": virtual + registry.openai_models()}


def _anthropic_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            block_type = block.get("type")
            if block_type == "text":
                parts.append(str(block.get("text") or ""))
            elif block_type == "tool_result":
                tool_content = block.get("content")
                parts.append(_anthropic_text_from_content(tool_content))
    return "\n".join(part for part in parts if part)


def _anthropic_content_to_openai(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content
    converted: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            converted.append({"type": "text", "text": str(block)})
            continue
        block_type = block.get("type")
        if block_type == "text":
            converted.append({"type": "text", "text": str(block.get("text") or "")})
        elif block_type == "image":
            source = block.get("source") if isinstance(block.get("source"), dict) else {}
            media_type = source.get("media_type") or "image/png"
            data = source.get("data") or ""
            if source.get("type") == "base64" and data:
                converted.append({"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{data}"}})
        elif block_type == "tool_result":
            converted.append({"type": "text", "text": _anthropic_text_from_content(block.get("content"))})
    return converted or ""


def _anthropic_tools_to_openai(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    # Anthropic tools carry input_schema at the top level; OpenAI-compatible
    # providers expect the function wrapper with parameters.
    converted = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description") or "",
                "parameters": tool.get("input_schema") or {"type": "object", "properties": {}},
            },
        }
        for tool in tools or []
        if isinstance(tool, dict) and tool.get("name")
    ]
    return converted or None


def _anthropic_to_chat_request(request: AnthropicMessagesRequest) -> ChatCompletionRequest:
    messages: list[ChatMessage] = []
    if request.system:
        messages.append(ChatMessage(role="system", content=_anthropic_text_from_content(request.system)))
    for message in request.messages:
        role = str(message.get("role") or "user")
        content = message.get("content")
        if role == "assistant" and isinstance(content, list):
            tool_calls = [
                {
                    "id": str(block.get("id") or f"call_{uuid.uuid4().hex[:24]}"),
                    "type": "function",
                    "function": {"name": str(block.get("name") or ""), "arguments": json.dumps(block.get("input") or {})},
                }
                for block in content
                if isinstance(block, dict) and block.get("type") == "tool_use"
            ]
            rest = [block for block in content if not (isinstance(block, dict) and block.get("type") == "tool_use")]
            if tool_calls:
                messages.append(ChatMessage(role="assistant", content=_anthropic_content_to_openai(rest) or None, tool_calls=tool_calls))
                continue
        elif isinstance(content, list):
            # tool_result blocks answer the assistant's tool_calls: they must become
            # role:"tool" messages, not user text, or providers lose the pairing.
            rest = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    messages.append(
                        ChatMessage(
                            role="tool",
                            content=_anthropic_text_from_content(block.get("content")),
                            tool_call_id=str(block.get("tool_use_id") or ""),
                        )
                    )
                else:
                    rest.append(block)
            if rest:
                messages.append(ChatMessage(role=role, content=_anthropic_content_to_openai(rest)))
            continue
        messages.append(ChatMessage(role=role, content=_anthropic_content_to_openai(content)))
    return ChatCompletionRequest(
        model=request.model,
        messages=messages,
        tools=_anthropic_tools_to_openai(request.tools),
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        stream=False,
    )


def _openai_message_to_anthropic_content(message: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    content = message.get("content")
    if isinstance(content, str):
        if content:
            blocks.append({"type": "text", "text": content})
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                blocks.append({"type": "text", "text": str(item.get("text") or "")})
    elif content is not None:
        blocks.append({"type": "text", "text": str(content)})
    for call in message.get("tool_calls") or []:
        function = (call or {}).get("function") or {}
        try:
            tool_input = json.loads(function.get("arguments") or "{}")
        except Exception:
            tool_input = {}
        blocks.append(
            {
                "type": "tool_use",
                "id": str(call.get("id") or f"toolu_{uuid.uuid4().hex[:24]}"),
                "name": str(function.get("name") or ""),
                "input": tool_input if isinstance(tool_input, dict) else {},
            }
        )
    return blocks or [{"type": "text", "text": ""}]


def _anthropic_usage(openai_usage: Any) -> dict[str, int]:
    usage = openai_usage if isinstance(openai_usage, dict) else {}
    return {
        "input_tokens": int(usage.get("prompt_tokens") or 0),
        "output_tokens": int(usage.get("completion_tokens") or 0),
    }


def _anthropic_stop_reason(openai_finish_reason: Any) -> str:
    if openai_finish_reason == "length":
        return "max_tokens"
    if openai_finish_reason == "tool_calls":
        return "tool_use"
    return "end_turn"


def _chat_body_to_anthropic(body: dict[str, Any], requested_model: str) -> dict[str, Any]:
    choices = body.get("choices") if isinstance(body.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    stop_reason = "tool_use" if message.get("tool_calls") else _anthropic_stop_reason(choice.get("finish_reason"))
    return {
        "id": body.get("id") or f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": body.get("model") or requested_model,
        "content": _openai_message_to_anthropic_content(message),
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": _anthropic_usage(body.get("usage")),
    }


def _anthropic_stream_from_message(message: dict[str, Any]) -> Iterator[bytes]:
    start = {key: value for key, value in message.items() if key not in ("content", "stop_reason", "stop_sequence")}
    start["content"] = []
    yield f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': start})}\n\n".encode()
    content = message.get("content") if isinstance(message.get("content"), list) else []
    for index, block in enumerate(content):
        start_block = block
        if isinstance(block, dict) and block.get("type") == "tool_use":
            # Anthropic streams tool input via input_json_delta; the start block
            # carries an empty input, mirroring the real API.
            start_block = {**block, "input": {}}
        yield f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': index, 'content_block': start_block})}\n\n".encode()
        if isinstance(block, dict) and block.get("type") == "text":
            yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': index, 'delta': {'type': 'text_delta', 'text': block.get('text') or ''}})}\n\n".encode()
        elif isinstance(block, dict) and block.get("type") == "tool_use":
            yield f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': index, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(block.get('input') or {})}})}\n\n".encode()
        yield f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': index})}\n\n".encode()
    delta = {"stop_reason": message.get("stop_reason") or "end_turn", "stop_sequence": message.get("stop_sequence")}
    yield f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': delta, 'usage': message.get('usage') or {}})}\n\n".encode()
    yield b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n"


def _usage_from_sse_line(line: bytes) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith(b"data:"):
        return None
    data = line[5:].strip()
    if not data or data == b"[DONE]":
        return None
    try:
        parsed = json.loads(data)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    usage = parsed.get("usage")
    if not isinstance(usage, dict):
        # Groq reports stream usage under x_groq instead of the OpenAI field.
        x_groq = parsed.get("x_groq")
        usage = x_groq.get("usage") if isinstance(x_groq, dict) else None
    return usage if isinstance(usage, dict) and usage.get("total_tokens") else None


def _error_from_sse_line(line: bytes) -> dict[str, Any] | None:
    # Some aggregators (OpenRouter-style, e.g. opencode zen) start a 200 SSE
    # stream and then emit an in-band `data: {"error": {...}}` chunk when the
    # upstream provider fails mid-generation. The OpenAI SDK raises on any
    # such chunk regardless of earlier `choices` content, so this must be
    # treated as a provider failure rather than forwarded as success.
    line = line.strip()
    if not line.startswith(b"data:"):
        return None
    data = line[5:].strip()
    if not data or data == b"[DONE]":
        return None
    try:
        parsed = json.loads(data)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    error = parsed.get("error")
    return error if isinstance(error, dict) and (error.get("message") or error.get("code")) else None


def _stream_and_persist_usage(
    body: Iterable[bytes],
    request_id: str,
    selected: Any,
    capability: str,
    agent_name: str | None,
    tokens_raw: int | None = None,
    tokens_compacted: int | None = None,
    demand: str | None = None,
) -> Iterator[bytes]:
    usage: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    buffer = b""
    try:
        for chunk in body:
            buffer += chunk
            *lines, buffer = buffer.split(b"\n")
            out = b""
            for line in lines:
                error = _error_from_sse_line(line)
                if error is not None:
                    break
                usage = _usage_from_sse_line(line) or usage
                out += line + b"\n"
            if out:
                yield out
            if error is not None:
                break
        else:
            error = _error_from_sse_line(buffer)
            if error is None:
                usage = _usage_from_sse_line(buffer) or usage
                if buffer:
                    yield buffer
    finally:
        if error is not None:
            record_provider_failure(selected.provider)
            metadata = error.get("metadata") if isinstance(error.get("metadata"), dict) else {}
            error_type = f"stream_{metadata.get('error_type') or error.get('code') or 'error'}"
            try:
                persist_route_event(request_id, selected.id, capability, "provider_error", error_type, agent_name=agent_name, tokens_raw=tokens_raw, tokens_compacted=tokens_compacted, demand=demand)
            except Exception:
                pass
            try:
                mark_runtime_failure_unhealthy(selected, None, f"runtime_{error_type}")
            except Exception:
                pass
        else:
            record_provider_success(selected.provider)
            record_sticky(agent_name, demand, selected.id)
            try:
                persist_route_event(request_id, selected.id, capability, "success", None, usage=usage, agent_name=agent_name, tokens_raw=tokens_raw, tokens_compacted=tokens_compacted, demand=demand, provider_model=selected.provider_model)
            except Exception:
                pass

    if error is not None:
        yield b"data: [DONE]\n\n"


@app.post("/v1/chat/completions")
def chat_completions(request: ChatCompletionRequest, raw_request: Request):
    # Attribute the request to the agent whose API key is on the Authorization header.
    # Agent lookup must never break routing: a failing agent store keeps serving.
    agent_name: str | None = None
    agent_lookup_failed = False
    authorization = raw_request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        try:
            agent_name = find_agent_by_key(authorization[len("Bearer "):].strip())
        except Exception:
            agent_name = None
            agent_lookup_failed = True
    if agent_name is None and not agent_lookup_failed:
        # All consumption must be attributed to an agent: once at least one agent is
        # registered, /v1 rejects missing/unknown keys instead of routing anonymously.
        # Stays open during first-time setup (no agents yet) and whenever the agent
        # store is unreachable — DB failures must never break routing.
        try:
            protected = has_any_agent()
        except Exception:
            protected = False
        if protected:
            return JSONResponse(
                status_code=401,
                content={
                    "error": {
                        "message": "A valid agent API key is required (Authorization: Bearer <agent-name>_…) — register the agent on the dashboard Agents page",
                        "type": "invalid_agent_key",
                    }
                },
            )
    if agent_name:
        # Opt-in monthly budget guard: only agents with budget_limit_usd set are
        # ever affected, and only 'block' mode short-circuits routing — 'alert'
        # (the default once a limit is set) stays visible-only on the dashboard.
        # Real cost is almost always 0 (free-tier-only router), so this is
        # measured against reference_cost — see app/pricing.py.
        try:
            budget = get_agent_budget(agent_name)
        except Exception:
            budget = None
        if budget and budget[0] is not None:
            limit_usd, action = budget
            try:
                spend = agent_month_spend(agent_name)
            except Exception:
                spend = None
            if spend is not None and spend >= limit_usd and action == "block":
                return JSONResponse(
                    status_code=429,
                    content={
                        "error": {
                            "message": f"Agent '{agent_name}' reached its monthly budget (${limit_usd:.2f} reference cost, ${spend:.2f} spent so far) — raise the limit or switch it to alert-only on the Agents dashboard page.",
                            "type": "budget_exceeded",
                        }
                    },
                )
    registry = load_registry_with_db_health()
    demand = resolve_demand(request.model, request.messages, bool(request.tools))
    capability = infer_capability(request, demand)
    candidates = registry.healthy_for_capability(capability)
    capability_downgraded = False
    if demand == "code" and not candidates:
        # Code-capable is a quality preference, not a hard requirement like vision
        # (a non-code model can still write code, just not as well) — so instead of
        # hard-failing when zero code-capable models are healthy, fall back to the
        # general pool. required_capability on the persisted route event records
        # the downgrade: demand="code" with required_capability != "code" is the
        # countable "no code option available" signal, distinct from ordinary
        # misclassification (where required_capability would still read "code").
        capability = "tool_call" if request.tools else "text"
        candidates = registry.healthy_for_capability(capability)
        capability_downgraded = True
    allowed: set[str] | None = None
    if agent_name:
        # Per-agent model controls: the agent routes only to its associated models.
        # An empty set (no providers registered under the agent) yields no candidates.
        # None (lookup failed) keeps routing unrestricted — DB failures never break routing.
        try:
            allowed = agent_allowed_models(agent_name)
        except Exception:
            allowed = None
        if allowed is not None:
            candidates = [model for model in candidates if model.id in allowed]
    # Auto-inclusion rule: when models deteriorate under load (429s/timeouts) the
    # healthy pool shrinks; below the minimum, models degraded *only by runtime
    # failures* re-enter as last-resort reserves instead of waiting out the
    # 10-minute cooldown — trying a possibly rate-limited model beats failing.
    reserves: list[Any] = []
    min_pool = int(os.environ.get("AUTO_INCLUDE_MIN_HEALTHY", "3"))
    if len(candidates) < min_pool:
        try:
            degraded_ids = runtime_degraded_models()
        except Exception:
            degraded_ids = set()
        if degraded_ids:
            from app.ranking import intelligence_score

            candidate_ids = {model.id for model in candidates}
            reserves = sorted(
                (
                    model
                    for model in registry.models
                    if model.enabled
                    and not model.healthy
                    and model.id in degraded_ids
                    and model.id not in candidate_ids
                    and capability in model.capabilities
                    and (allowed is None or model.id in allowed)
                ),
                key=lambda model: (model.tier, -intelligence_score(model.id)),
            )
    if demand:
        # Demand-based routing (auto / forgerouter/<demand>): try the configured chain for
        # the demand class first (or the rank-derived default), then every other healthy
        # candidate — small jobs stay on small models, preserving free-tier quotas.
        if capability_downgraded:
            # No configured/default chain applies to the downgraded general pool —
            # rank every healthy candidate best-to-worst (same dynamic_score used
            # to order every other chain) instead of a fixed demand-specific list.
            from app.ranking import dynamic_score

            performance = model_performance_cached()
            chain_ids = [model.id for model in sorted(candidates, key=lambda model: -dynamic_score(model.id, performance))]
        else:
            try:
                chain_ids = get_demand_routes().get(demand) or []
            except Exception:
                chain_ids = []
            if not chain_ids:
                chain_ids = [model.id for model in default_chain(candidates, demand, performance=model_performance_cached())]
        order = {model_id: position for position, model_id in enumerate(chain_ids)}
        # Sticky routing: the last model that succeeded for this agent+demand goes
        # first (even ahead of the chain head) — staying on the same model across a
        # conversation preserves the provider's prompt cache.
        sticky_id = sticky_model(agent_name, demand)
        candidates = sorted(candidates, key=lambda model: (model.id != sticky_id, order.get(model.id, len(order) + model.tier), model.tier))
    elif request.model and request.model != "auto":
        # The requested model is a preference, not an exclusive filter: it is tried first,
        # but the remaining healthy candidates stay as automatic fallback — hitting a
        # free-tier limit (429) must never stop the caller's process.
        candidates = sorted(candidates, key=lambda model: model.id != request.model)
    if reserves:
        # Reserves go strictly after the healthy candidates, in tier order.
        candidates = candidates + reserves
    # Circuit breaker: models of a provider that just failed repeatedly sort last
    # (deprioritized, never excluded — the last resort must stay reachable).
    tripped = {model.provider: breaker_open(model.provider) for model in candidates}
    if any(tripped.values()):
        candidates = sorted(candidates, key=lambda model: tripped[model.provider])
    if not candidates:
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": f"No healthy provider available for capability: {capability}",
                    "type": "no_healthy_provider",
                    "capability": capability,
                }
            },
        )
    request_id = str(uuid.uuid4())
    last_error: dict[str, Any] | None = None
    # exclude_none: strict providers (Mistral, Cloudflare) reject explicit nulls
    # ("name": null → 422 extra_forbidden); lenient ones ignore them either way.
    raw_messages = [message.model_dump(exclude_none=True) for message in request.messages]
    try:
        tokens_raw = count_tokens(raw_messages, request.tools)
    except Exception:
        tokens_raw = None
    try:
        compaction_on = context_compaction_enabled()
    except Exception:
        compaction_on = True
    if compaction_on:
        try:
            messages_for_payload = normalize_messages(raw_messages)
        except Exception:
            messages_for_payload = raw_messages
    else:
        messages_for_payload = raw_messages
    try:
        tokens_compacted = count_tokens(messages_for_payload, request.tools)
    except Exception:
        tokens_compacted = None
    for selected in candidates:
        payload = build_chat_payload(
            selected,
            messages_for_payload,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            tools=request.tools,
            stream=request.stream,
        )
        try:
            status_code, body = chat_completion(selected, payload)
            # Internal marker from the provider client: Retry-After on a 429/5xx
            # becomes this model's runtime cooldown (never leaks to the caller).
            retry_after = body.pop("_proxyrouter_retry_after", None) if isinstance(body, dict) else None
            if status_code < 400:
                if request.stream:
                    # Usage arrives in the final SSE chunk (stream_options.include_usage),
                    # so the route event is persisted after the stream completes.
                    stream_body = _stream_and_persist_usage(body, request_id, selected, capability, agent_name, tokens_raw=tokens_raw, tokens_compacted=tokens_compacted, demand=demand)
                    return StreamingResponse(stream_body, media_type="text/event-stream", headers={"x-proxyrouter-request-id": request_id, "x-proxyrouter-model": selected.id})
                # A provider can return HTTP 200 with a body that is itself an error
                # (no choices, empty content, quota/auth text) — treat that the same
                # as an HTTP error so the next candidate gets a chance.
                silent_failure = detect_silent_failure(body) if isinstance(body, dict) else "non_json_response"
                if silent_failure is None:
                    record_provider_success(selected.provider)
                    record_sticky(agent_name, demand, selected.id)
                    usage = body.get("usage") if isinstance(body, dict) and isinstance(body.get("usage"), dict) else None
                    try:
                        persist_route_event(request_id, selected.id, capability, "success", None, usage=usage, agent_name=agent_name, tokens_raw=tokens_raw, tokens_compacted=tokens_compacted, demand=demand, provider_model=selected.provider_model)
                    except Exception:
                        pass
                    return JSONResponse(status_code=status_code, content=body, headers={"x-proxyrouter-request-id": request_id, "x-proxyrouter-model": selected.id})
                error_type = f"silent_{silent_failure}"
            else:
                error_type = f"http_{status_code}"
            record_provider_failure(selected.provider)
            last_error = {"status_code": status_code, "body": body, "model_id": selected.id}
            try:
                persist_route_event(request_id, selected.id, capability, "provider_error", error_type, agent_name=agent_name, tokens_raw=tokens_raw, tokens_compacted=tokens_compacted, demand=demand)
            except Exception:
                pass
            try:
                mark_runtime_failure_unhealthy(selected, status_code, f"runtime_{error_type}", cooldown_seconds=retry_after)
            except Exception:
                pass
        except Exception as exc:
            record_provider_failure(selected.provider)
            last_error = {"status_code": 502, "body": {"error": {"message": str(exc)}}, "model_id": selected.id}
            try:
                persist_route_event(request_id, selected.id, capability, "failed", type(exc).__name__, agent_name=agent_name, tokens_raw=tokens_raw, tokens_compacted=tokens_compacted, demand=demand)
            except Exception:
                pass
            try:
                mark_runtime_failure_unhealthy(selected, None, f"runtime_{type(exc).__name__}")
            except Exception:
                pass
    return JSONResponse(
        status_code=502,
        content={"error": {"message": "All healthy providers failed", "type": "all_providers_failed", "last_error": last_error}},
        headers={"x-proxyrouter-request-id": request_id},
    )


@app.post("/v1/messages")
def anthropic_messages(request: AnthropicMessagesRequest, raw_request: Request):
    chat_request = _anthropic_to_chat_request(request)
    response = chat_completions(chat_request, raw_request)
    if not isinstance(response, JSONResponse):
        return response
    try:
        body = json.loads(response.body.decode("utf-8"))
    except Exception:
        body = {}
    if response.status_code >= 400:
        return JSONResponse(status_code=response.status_code, content=body, headers=dict(response.headers))
    message = _chat_body_to_anthropic(body, request.model)
    headers = {
        key: value
        for key, value in dict(response.headers).items()
        if key.lower().startswith("x-proxyrouter-")
    }
    if request.stream:
        return StreamingResponse(_anthropic_stream_from_message(message), media_type="text/event-stream", headers=headers)
    return JSONResponse(status_code=response.status_code, content=message, headers=headers)


class ResponsesRequest(BaseModel):
    model_config = {"extra": "allow"}

    model: str = "auto"
    input: Any = None
    instructions: str | None = None
    tools: list[dict[str, Any]] | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    stream: bool = False


def _responses_text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return "" if content is None else str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and block.get("type") in ("input_text", "output_text", "text"):
            parts.append(str(block.get("text") or ""))
    return "\n".join(part for part in parts if part)


def _responses_content_to_openai(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content
    converted: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, dict):
            converted.append({"type": "text", "text": str(block)})
            continue
        block_type = block.get("type")
        if block_type in ("input_text", "output_text", "text"):
            converted.append({"type": "text", "text": str(block.get("text") or "")})
        elif block_type == "input_image":
            url = block.get("image_url")
            if isinstance(url, dict):
                url = url.get("url")
            if url:
                converted.append({"type": "image_url", "image_url": {"url": url}})
    return converted or ""


def _responses_tools_to_openai(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    # Responses API tools are flat ({"type":"function","name":...,"parameters":...});
    # OpenAI-compatible Chat Completions providers expect the nested function wrapper.
    converted = [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool.get("description") or "",
                "parameters": tool.get("parameters") or {"type": "object", "properties": {}},
            },
        }
        for tool in tools or []
        if isinstance(tool, dict) and tool.get("type", "function") == "function" and tool.get("name")
    ]
    return converted or None


def _responses_to_chat_request(request: ResponsesRequest) -> ChatCompletionRequest:
    messages: list[ChatMessage] = []
    if request.instructions:
        messages.append(ChatMessage(role="system", content=request.instructions))

    raw_input = request.input
    if isinstance(raw_input, str):
        items: list[Any] = [{"type": "message", "role": "user", "content": raw_input}]
    elif isinstance(raw_input, list):
        items = raw_input
    else:
        items = []

    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = item.get("type") or "message"
        if item_type == "message":
            role = str(item.get("role") or "user")
            messages.append(ChatMessage(role=role, content=_responses_content_to_openai(item.get("content"))))
        elif item_type == "function_call":
            call_id = str(item.get("call_id") or item.get("id") or f"call_{uuid.uuid4().hex[:24]}")
            arguments = item.get("arguments")
            messages.append(
                ChatMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": str(item.get("name") or ""),
                                "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments or {}),
                            },
                        }
                    ],
                )
            )
        elif item_type == "function_call_output":
            output = item.get("output")
            messages.append(
                ChatMessage(
                    role="tool",
                    tool_call_id=str(item.get("call_id") or ""),
                    content=output if isinstance(output, str) else _responses_text_from_content(output),
                )
            )
        # Other item types (reasoning traces, etc.) carry provider-specific state
        # we don't forward — the transcript text/tool pairing above already
        # reconstructs everything a Chat Completions provider needs.

    return ChatCompletionRequest(
        model=request.model,
        messages=messages,
        tools=_responses_tools_to_openai(request.tools),
        temperature=request.temperature,
        max_tokens=request.max_output_tokens,
        stream=False,
    )


def _chat_message_to_responses_output(message: dict[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    content = message.get("content")
    text = content if isinstance(content, str) else _responses_text_from_content(content)
    tool_calls = message.get("tool_calls") or []
    if text or not tool_calls:
        output.append(
            {
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex}",
                "status": "completed",
                "role": "assistant",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        )
    for call in tool_calls:
        function = (call or {}).get("function") or {}
        output.append(
            {
                "type": "function_call",
                "id": f"fc_{uuid.uuid4().hex}",
                "call_id": str(call.get("id") or f"call_{uuid.uuid4().hex[:24]}"),
                "name": str(function.get("name") or ""),
                "arguments": function.get("arguments") or "{}",
                "status": "completed",
            }
        )
    return output


def _responses_usage(openai_usage: Any) -> dict[str, int]:
    usage = openai_usage if isinstance(openai_usage, dict) else {}
    input_tokens = int(usage.get("prompt_tokens") or 0)
    output_tokens = int(usage.get("completion_tokens") or 0)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(usage.get("total_tokens") or (input_tokens + output_tokens)),
    }


def _chat_body_to_responses(body: dict[str, Any], requested_model: str) -> dict[str, Any]:
    choices = body.get("choices") if isinstance(body.get("choices"), list) else []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
    finish_reason = choice.get("finish_reason")
    status = "incomplete" if finish_reason == "length" else "completed"
    response: dict[str, Any] = {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": int(time.time()),
        "status": status,
        "model": body.get("model") or requested_model,
        "output": _chat_message_to_responses_output(message),
        "usage": _responses_usage(body.get("usage")),
    }
    if status == "incomplete":
        response["incomplete_details"] = {"reason": "max_output_tokens"}
    return response


def _responses_stream_from_response(response: dict[str, Any]) -> Iterator[bytes]:
    seq = 0

    def emit(event_type: str, **fields: Any) -> bytes:
        nonlocal seq
        seq += 1
        payload = {"type": event_type, "sequence_number": seq, **fields}
        return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n".encode()

    in_progress = {**response, "status": "in_progress", "output": []}
    yield emit("response.created", response=in_progress)
    yield emit("response.in_progress", response=in_progress)

    output = response.get("output") if isinstance(response.get("output"), list) else []
    for index, item in enumerate(output):
        item_type = item.get("type")
        start_item = dict(item)
        if item_type == "message":
            start_item["content"] = []
        elif item_type == "function_call":
            start_item["arguments"] = ""
        yield emit("response.output_item.added", output_index=index, item=start_item)

        if item_type == "message":
            for content_index, part in enumerate(item.get("content") or []):
                item_id = item["id"]
                yield emit(
                    "response.content_part.added",
                    item_id=item_id,
                    output_index=index,
                    content_index=content_index,
                    part={**part, "text": ""},
                )
                text = part.get("text") or ""
                if text:
                    yield emit(
                        "response.output_text.delta",
                        item_id=item_id,
                        output_index=index,
                        content_index=content_index,
                        delta=text,
                    )
                yield emit(
                    "response.output_text.done",
                    item_id=item_id,
                    output_index=index,
                    content_index=content_index,
                    text=text,
                )
                yield emit(
                    "response.content_part.done",
                    item_id=item_id,
                    output_index=index,
                    content_index=content_index,
                    part=part,
                )
        elif item_type == "function_call":
            arguments = item.get("arguments") or "{}"
            yield emit("response.function_call_arguments.delta", item_id=item["id"], output_index=index, delta=arguments)
            yield emit("response.function_call_arguments.done", item_id=item["id"], output_index=index, arguments=arguments)

        yield emit("response.output_item.done", output_index=index, item=item)

    yield emit("response.completed", response=response)


@app.post("/v1/responses")
def responses_endpoint(request: ResponsesRequest, raw_request: Request):
    chat_request = _responses_to_chat_request(request)
    response = chat_completions(chat_request, raw_request)
    if not isinstance(response, JSONResponse):
        return response
    try:
        body = json.loads(response.body.decode("utf-8"))
    except Exception:
        body = {}
    if response.status_code >= 400:
        return JSONResponse(status_code=response.status_code, content=body, headers=dict(response.headers))
    result = _chat_body_to_responses(body, request.model)
    headers = {
        key: value
        for key, value in dict(response.headers).items()
        if key.lower().startswith("x-proxyrouter-")
    }
    if request.stream:
        return StreamingResponse(_responses_stream_from_response(result), media_type="text/event-stream", headers=headers)
    return JSONResponse(status_code=response.status_code, content=result, headers=headers)


def require_admin(request: Request) -> JSONResponse | None:
    """Admin actions are authorized by a logged-in dashboard session or by any
    registered agent's API key (each agent carries its own AGENTE_API_KEY in
    ai_router.agents — there is no master key in the environment). While no
    agent exists yet (or the DB is unreachable), admin stays open so the
    first-time setup can register one."""
    token = bearer_token(request)
    if token:
        try:
            if session_user(token):
                return None
        except Exception:
            pass
        try:
            if find_agent_by_key(token):
                return None
        except Exception:
            pass
    try:
        protected = has_any_agent()
    except Exception:
        protected = False
    if not protected:
        return None
    return JSONResponse(
        status_code=401,
        content={"error": {"message": "Unauthorized", "type": "unauthorized"}},
    )


class LoginPayload(BaseModel):
    username: str
    password: str


class ChangeCredentialsPayload(BaseModel):
    current_password: str
    new_password: str
    new_username: str = ""  # empty = keep the current username


def bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    return authorization[len("Bearer "):].strip() if authorization.startswith("Bearer ") else ""


@app.post("/auth/login")
def auth_login(payload: LoginPayload):
    try:
        ensure_default_user()
        user = authenticate_user(payload.username.strip(), payload.password)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "Login store unavailable (database unreachable)", "type": "auth_store_unavailable"}},
        )
    if not user:
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid username or password", "type": "invalid_credentials"}},
        )
    token = create_session(user["user_id"])
    return {
        "token": token,
        "username": user["username"],
        "must_change_password": user["must_change_password"],
        "is_admin": user.get("is_admin", False),
        "full_name": user.get("full_name"),
        "email": user.get("email"),
        "avatar_data_url": user.get("avatar_data_url"),
        "permissions": user_permissions(user),
    }


@app.post("/auth/sso")
def auth_sso(request: Request):
    """Trusted single sign-on from ForgeHub. Exchanges the shared secret
    (FORGEHUB_SSO_SECRET — sent server-to-server by the ForgeHub backend,
    never shipped to a browser) for a short-lived regular dashboard session,
    so the ForgeHub iframe skips the login screen. Disabled unless the env
    var is set on this side; the secret comparison is constant-time. Signs
    in as the dashboard's primary user, so first-access password change is
    still enforced before anything renders."""
    secret = os.environ.get("FORGEHUB_SSO_SECRET", "")
    provided = request.headers.get("x-sso-secret", "")
    if not secret or not provided or not secrets.compare_digest(provided, secret):
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "SSO is not enabled or the secret does not match", "type": "sso_denied"}},
        )
    try:
        ensure_default_user()
        user = first_user()
        if not user:
            raise RuntimeError("no dashboard user")
        token = create_session(user["user_id"], days=1)
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"error": {"message": "Login store unavailable (database unreachable)", "type": "auth_store_unavailable"}},
        )
    return {"token": token, "username": user["username"], "must_change_password": user["must_change_password"]}


@app.get("/auth/me")
def auth_me(request: Request):
    try:
        user = session_user(bearer_token(request))
    except Exception:
        user = None
    if not user:
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid or expired session", "type": "invalid_session"}},
        )
    return {
        "username": user["username"],
        "must_change_password": user["must_change_password"],
        "is_admin": user.get("is_admin", False),
        "full_name": user.get("full_name"),
        "email": user.get("email"),
        "avatar_data_url": user.get("avatar_data_url"),
        "permissions": user_permissions(user),
    }


def _email_conflict(email: str, exclude_user_id: int | None = None) -> bool:
    lowered = email.lower()
    return any(
        (u.get("email") or "").lower() == lowered and u["user_id"] != exclude_user_id
        for u in list_users()
    )


# Avatars arrive as data: URLs, downscaled to 256px client-side — anything
# bigger than this means the client didn't resize (or isn't an image).
_MAX_AVATAR_CHARS = 1_500_000


def _avatar_rejection(value: str | None) -> JSONResponse | None:
    if not value:
        return None
    if not value.startswith("data:image/") or len(value) > _MAX_AVATAR_CHARS:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Avatar must be a data:image URI of at most ~1MB", "type": "invalid_avatar"}},
        )
    return None


class MeUpdatePayload(BaseModel):
    full_name: str | None = None
    username: str | None = None
    email: str | None = None
    # None = not sent; empty string = remove the photo.
    avatar_data_url: str | None = None


@app.patch("/auth/me")
def auth_me_update(payload: MeUpdatePayload, request: Request):
    """Self-service account edit (any authenticated user, not just admins):
    display name and username only — password has its own endpoint, and
    admin/active/profile flags are strictly PATCH /auth/users territory."""
    try:
        user = session_user(bearer_token(request))
    except Exception:
        user = None
    if not user:
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid or expired session", "type": "invalid_session"}},
        )
    fields: dict = {}
    if payload.username is not None:
        new_username = payload.username.strip()
        if not new_username:
            return JSONResponse(status_code=400, content={"error": {"message": "Username cannot be empty", "type": "invalid_user"}})
        if any(u["username"] == new_username and u["user_id"] != user["user_id"] for u in list_users()):
            return JSONResponse(status_code=409, content={"error": {"message": f"Username '{new_username}' already exists", "type": "duplicate_username"}})
        fields["username"] = new_username
    if payload.full_name is not None:
        fields["full_name"] = payload.full_name.strip() or None
    if payload.email is not None:
        email = payload.email.strip()
        if email and _email_conflict(email, user["user_id"]):
            return JSONResponse(status_code=409, content={"error": {"message": f"E-mail '{email}' is already in use", "type": "duplicate_email"}})
        fields["email"] = email or None
    if payload.avatar_data_url is not None:
        rejection = _avatar_rejection(payload.avatar_data_url)
        if rejection:
            return rejection
        fields["avatar_data_url"] = payload.avatar_data_url or None
    update_user(user["user_id"], fields)
    fresh = session_user(bearer_token(request)) or user
    return {
        "username": fresh["username"],
        "must_change_password": fresh["must_change_password"],
        "is_admin": fresh.get("is_admin", False),
        "full_name": fresh.get("full_name"),
        "email": fresh.get("email"),
        "avatar_data_url": fresh.get("avatar_data_url"),
        "permissions": user_permissions(fresh),
    }


# ---------------------------------------------------------------------------
# User accounts + access profiles administration (ForgeHub-style RBAC).
# Admin-only: a valid dashboard session whose user has is_admin. Business
# rules enforced here, matching ForgeHub's users route: you cannot delete
# yourself, and the last active admin can never be deleted or demoted.
# ---------------------------------------------------------------------------


def _admin_user(request: Request) -> dict | None:
    try:
        user = session_user(bearer_token(request))
    except Exception:
        return None
    return user if user and user.get("is_admin") else None


_ADMIN_DENIED = {"error": {"message": "Administrator session required", "type": "admin_required"}}


class UserCreatePayload(BaseModel):
    username: str
    password: str
    full_name: str = ""
    email: str = ""
    is_admin: bool = False
    profile_id: int | None = None
    avatar_data_url: str | None = None


class UserUpdatePayload(BaseModel):
    username: str | None = None
    password: str | None = None
    full_name: str | None = None
    is_admin: bool | None = None
    is_active: bool | None = None
    profile_id: int | None = None
    clear_profile: bool = False  # explicit, since profile_id None also means "not sent"
    email: str | None = None
    # None = not sent; empty string = remove the photo.
    avatar_data_url: str | None = None


class ProfilePermissionPayload(BaseModel):
    module: str
    can_view: bool = False
    can_query: bool = False
    can_write: bool = False
    can_delete: bool = False


class ProfilePayload(BaseModel):
    name: str
    description: str = ""
    permissions: list[ProfilePermissionPayload] = Field(default_factory=list)


@app.get("/auth/users")
def auth_users_list(request: Request):
    if not _admin_user(request):
        return JSONResponse(status_code=403, content=_ADMIN_DENIED)
    return {"users": list_users()}


@app.post("/auth/users")
def auth_users_create(payload: UserCreatePayload, request: Request):
    if not _admin_user(request):
        return JSONResponse(status_code=403, content=_ADMIN_DENIED)
    username = payload.username.strip()
    if not username or len(payload.password) < 4:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Username and a password with at least 4 characters are required", "type": "invalid_user"}},
        )
    if any(u["username"] == username for u in list_users()):
        return JSONResponse(
            status_code=409,
            content={"error": {"message": f"Username '{username}' already exists", "type": "duplicate_username"}},
        )
    rejection = _avatar_rejection(payload.avatar_data_url)
    if rejection:
        return rejection
    email = payload.email.strip()
    if email and _email_conflict(email):
        return JSONResponse(status_code=409, content={"error": {"message": f"E-mail '{email}' is already in use", "type": "duplicate_email"}})
    user_id = create_user(
        username, payload.password, payload.full_name.strip() or None,
        payload.is_admin, payload.profile_id, payload.avatar_data_url or None, email or None,
    )
    return {"user_id": user_id, "username": username}


@app.patch("/auth/users/{user_id}")
def auth_users_update(user_id: int, payload: UserUpdatePayload, request: Request):
    admin = _admin_user(request)
    if not admin:
        return JSONResponse(status_code=403, content=_ADMIN_DENIED)
    fields: dict = {}
    if payload.username is not None and payload.username.strip():
        fields["username"] = payload.username.strip()
    if payload.password:
        if len(payload.password) < 4:
            return JSONResponse(status_code=400, content={"error": {"message": "Password needs at least 4 characters", "type": "weak_password"}})
        fields["password"] = payload.password
    if payload.full_name is not None:
        fields["full_name"] = payload.full_name.strip() or None
    if payload.is_admin is not None:
        fields["is_admin"] = payload.is_admin
    if payload.is_active is not None:
        fields["is_active"] = payload.is_active
    if payload.clear_profile:
        fields["profile_id"] = None
    elif payload.profile_id is not None:
        fields["profile_id"] = payload.profile_id
    if payload.email is not None:
        email = payload.email.strip()
        if email and _email_conflict(email, user_id):
            return JSONResponse(status_code=409, content={"error": {"message": f"E-mail '{email}' is already in use", "type": "duplicate_email"}})
        fields["email"] = email or None
    if payload.avatar_data_url is not None:
        rejection = _avatar_rejection(payload.avatar_data_url)
        if rejection:
            return rejection
        fields["avatar_data_url"] = payload.avatar_data_url or None
    # Last-admin protection: demoting or deactivating the only active admin
    # would lock everyone out of user management for good.
    target = next((u for u in list_users() if u["user_id"] == user_id), None)
    if not target:
        return JSONResponse(status_code=404, content={"error": {"message": "User not found", "type": "not_found"}})
    losing_admin = target["is_admin"] and target["is_active"] and (
        fields.get("is_admin") is False or fields.get("is_active") is False
    )
    if losing_admin and count_active_admins() <= 1:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Cannot demote or deactivate the last active administrator", "type": "last_admin"}},
        )
    update_user(user_id, fields)
    return {"ok": True}


@app.delete("/auth/users/{user_id}")
def auth_users_delete(user_id: int, request: Request):
    admin = _admin_user(request)
    if not admin:
        return JSONResponse(status_code=403, content=_ADMIN_DENIED)
    if user_id == admin["user_id"]:
        return JSONResponse(status_code=400, content={"error": {"message": "Cannot delete yourself", "type": "self_delete"}})
    target = next((u for u in list_users() if u["user_id"] == user_id), None)
    if not target:
        return JSONResponse(status_code=404, content={"error": {"message": "User not found", "type": "not_found"}})
    if target["is_admin"] and target["is_active"] and count_active_admins() <= 1:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Cannot delete the last active administrator", "type": "last_admin"}},
        )
    delete_user(user_id)
    return {"ok": True}


@app.get("/auth/profiles")
def auth_profiles_list(request: Request):
    if not _admin_user(request):
        return JSONResponse(status_code=403, content=_ADMIN_DENIED)
    return {"profiles": list_profiles()}


@app.post("/auth/profiles")
def auth_profiles_create(payload: ProfilePayload, request: Request):
    if not _admin_user(request):
        return JSONResponse(status_code=403, content=_ADMIN_DENIED)
    name = payload.name.strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": {"message": "Profile name is required", "type": "invalid_profile"}})
    if any(p["name"] == name for p in list_profiles()):
        return JSONResponse(status_code=409, content={"error": {"message": f"Profile '{name}' already exists", "type": "duplicate_profile"}})
    profile_id = save_profile(name, payload.description.strip() or None, [p.model_dump() for p in payload.permissions])
    return {"profile_id": profile_id, "name": name}


@app.patch("/auth/profiles/{profile_id}")
def auth_profiles_update(profile_id: int, payload: ProfilePayload, request: Request):
    if not _admin_user(request):
        return JSONResponse(status_code=403, content=_ADMIN_DENIED)
    name = payload.name.strip()
    if not name:
        return JSONResponse(status_code=400, content={"error": {"message": "Profile name is required", "type": "invalid_profile"}})
    if any(p["name"] == name and p["profile_id"] != profile_id for p in list_profiles()):
        return JSONResponse(status_code=409, content={"error": {"message": f"Profile '{name}' already exists", "type": "duplicate_profile"}})
    save_profile(name, payload.description.strip() or None, [p.model_dump() for p in payload.permissions], profile_id)
    return {"ok": True}


@app.delete("/auth/profiles/{profile_id}")
def auth_profiles_delete(profile_id: int, request: Request):
    if not _admin_user(request):
        return JSONResponse(status_code=403, content=_ADMIN_DENIED)
    if not delete_profile(profile_id):
        return JSONResponse(status_code=404, content={"error": {"message": "Profile not found", "type": "not_found"}})
    return {"ok": True}


@app.post("/auth/change-password")
def auth_change_password(payload: ChangeCredentialsPayload, request: Request):
    try:
        user = session_user(bearer_token(request))
    except Exception:
        user = None
    if not user:
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "Invalid or expired session", "type": "invalid_session"}},
        )
    new_password = payload.new_password.strip()
    if len(new_password) < 4 or new_password == "admin":
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Pick a new password with at least 4 characters (and not 'admin')", "type": "weak_password"}},
        )
    try:
        updated = change_credentials(user["user_id"], payload.current_password, payload.new_username, new_password)
    except Exception as exc:
        duplicate = "unique" in str(exc).lower() or "duplicate" in str(exc).lower()
        return JSONResponse(
            status_code=409 if duplicate else 500,
            content={"error": {"message": "Username already taken" if duplicate else str(exc), "type": "change_credentials_failed"}},
        )
    if not updated:
        return JSONResponse(
            status_code=401,
            content={"error": {"message": "Current password is incorrect", "type": "invalid_credentials"}},
        )
    return {"status": "changed", "username": updated["username"], "must_change_password": False}


@app.post("/auth/logout")
def auth_logout(request: Request):
    try:
        delete_session(bearer_token(request))
    except Exception:
        pass
    return {"status": "logged_out"}


def _generate_agent_key(name: str) -> str:
    # The agent name is baked into the key itself, as a PREFIX (<slug>_<random>) rather
    # than a suffix, because every masked display (mask_secret, dashboards) only ever
    # shows the first few characters of a secret, never the tail — a key pasted into
    # the wrong agent's config is only visually obvious at a glance if the name is the
    # part that survives truncation. This is what actually would have caught Scriba
    # silently running with Athos's key.
    slug = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-") or "agent"
    return f"{slug}_{secrets.token_urlsafe(30)}"


AGENT_KINDS = ("agent", "service")


class AgentPayload(BaseModel):
    name: str
    api_key: str = ""  # optional: pre-generated by the dashboard token generator; empty = server generates
    description: str = ""  # free-text purpose, e.g. "used by the Hermes auxiliary tasks"
    kind: str = "agent"  # "agent" = real Hermes profile (gateway/Telegram/KB); "service" = internal
    # caller that only needs a routing identity/API key (e.g. Hindsight) — not a Hermes profile.


@app.get("/admin/agents")
def admin_agents_list(request: Request, days: int = 30):
    # Read-only: agent list with usage stats. API keys are masked, never exposed here.
    from app.registry import mask_secret

    try:
        agents = list_agents_with_usage(max(1, min(days, 365)))
    except Exception:
        return {"agents": [], "source": "db_unavailable"}
    for agent in agents:
        agent["api_key_masked"] = mask_secret(agent.pop("api_key", "") or "")
    return {"agents": agents, "source": "database"}


@app.post("/admin/agents")
def admin_agent_create(payload: AgentPayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    name = payload.name.strip()
    if not name:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Agent name is required", "type": "invalid_payload"}},
        )
    kind = payload.kind.strip().lower() or "agent"
    if kind not in AGENT_KINDS:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": f"kind must be one of {AGENT_KINDS}", "type": "invalid_payload"}},
        )
    api_key = payload.api_key.strip() or _generate_agent_key(name)
    try:
        create_agent(name, api_key, payload.description.strip(), kind)
    except Exception as exc:
        duplicate = "unique" in str(exc).lower() or "duplicate" in str(exc).lower()
        return JSONResponse(
            status_code=409 if duplicate else 500,
            content={"error": {"message": f"Agent already exists: {name}" if duplicate else str(exc), "type": "agent_create_failed"}},
        )
    # The full key is returned only on creation; afterwards it is masked everywhere.
    return {"status": "created", "agent": name, "api_key": api_key}


@app.post("/admin/agents/{name}/rotate-key")
def admin_agent_rotate_key(name: str, request: Request):
    """Generate a new API key for the agent. Model/provider controls are kept (tied to the agent, not the key).
    If the agent has a deploy-config (PUT /admin/agents/{name}/deploy-config), the new key is also
    written into the agent's own runtime config file and its service restarted — synchronously, in
    this same request, so a failure is reported back immediately rather than left as a silent stale
    key (see the Scriba/Athos key-mixup incident, 06-INCIDENTE-KEY-TROCADA-ENTRE-AGENTES.md)."""
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    old_key = get_agent_api_key(name)
    api_key = _generate_agent_key(name)
    try:
        rotated = rotate_agent_key(name, api_key)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "agent_rotate_failed"}},
        )
    if not rotated:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    deploy_result = {"applied": False, "status": "no_config", "detail": "No deploy-config set for this agent — key rotated in the database only."}
    if old_key:
        try:
            deploy_config = get_agent_deploy_config(name) or {}
        except Exception:
            deploy_config = {}
        deploy_result = apply_agent_deploy_config(
            old_key,
            api_key,
            deploy_config.get("config_path"),
            deploy_config.get("config_format"),
            deploy_config.get("restart_service"),
        )
    return {"status": "rotated", "agent": name, "api_key": api_key, "deploy": deploy_result}


@app.post("/admin/agents/{name}/duplicate")
def admin_agent_duplicate(name: str, payload: AgentPayload, request: Request):
    """Clone an agent: new name and key, same model/provider associations."""
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    new_name = payload.name.strip()
    if not new_name:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "New agent name is required", "type": "invalid_payload"}},
        )
    api_key = payload.api_key.strip() or _generate_agent_key(new_name)
    try:
        duplicated = duplicate_agent(name, new_name, api_key)
    except Exception as exc:
        duplicate = "unique" in str(exc).lower() or "duplicate" in str(exc).lower()
        return JSONResponse(
            status_code=409 if duplicate else 500,
            content={"error": {"message": f"Agent already exists: {new_name}" if duplicate else str(exc), "type": "agent_duplicate_failed"}},
        )
    if not duplicated:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    return {"status": "duplicated", "agent": new_name, "source": name, "api_key": api_key}


class AgentDescriptionPayload(BaseModel):
    description: str = ""


@app.put("/admin/agents/{name}/description")
def admin_agent_set_description(name: str, payload: AgentDescriptionPayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        updated = set_agent_description(name, payload.description.strip())
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "agent_description_failed"}},
        )
    if not updated:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    return {"status": "saved", "agent": name, "description": payload.description.strip()}


class AgentKindPayload(BaseModel):
    kind: str


@app.put("/admin/agents/{name}/kind")
def admin_agent_set_kind(name: str, payload: AgentKindPayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    kind = payload.kind.strip().lower()
    if kind not in AGENT_KINDS:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": f"kind must be one of {AGENT_KINDS}", "type": "invalid_payload"}},
        )
    try:
        updated = set_agent_kind(name, kind)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "agent_kind_failed"}},
        )
    if not updated:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    return {"status": "saved", "agent": name, "kind": kind}


class AgentDeployConfigPayload(BaseModel):
    config_path: str = ""  # empty = clear (rotate-key goes back to DB-only for this agent)
    config_format: str = ""  # "yaml" | "env" | "" (clear)
    config_key: str = ""  # documentation only today (e.g. providers.forgerouter.api_key or FORGEROUTER_API_KEY) — the actual write is an exact-match string replace, not a parser
    restart_service: str = ""  # systemd unit to restart after the write; empty = nothing to restart


@app.get("/admin/agents/{name}/deploy-config")
def admin_agent_get_deploy_config(name: str, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        config = get_agent_deploy_config(name)
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": {"message": str(exc), "type": "agent_deploy_config_failed"}})
    if config is None:
        return JSONResponse(status_code=404, content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}})
    return {"agent": name, **config}


@app.put("/admin/agents/{name}/deploy-config")
def admin_agent_set_deploy_config(name: str, payload: AgentDeployConfigPayload, request: Request):
    """Where this agent's own runtime config lives, so rotate-key can write the new key there
    directly (and restart its service) instead of leaving it silently stale."""
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    config_format = payload.config_format.strip() or None
    if config_format is not None and config_format not in ("yaml", "env"):
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "config_format must be 'yaml', 'env', or empty", "type": "invalid_payload"}},
        )
    try:
        updated = set_agent_deploy_config(
            name,
            payload.config_path.strip() or None,
            config_format,
            payload.config_key.strip() or None,
            payload.restart_service.strip() or None,
        )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"error": {"message": str(exc), "type": "agent_deploy_config_failed"}})
    if not updated:
        return JSONResponse(status_code=404, content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}})
    return {"status": "saved", "agent": name}


class AgentNamePayload(BaseModel):
    name: str


@app.put("/admin/agents/{name}/name")
def admin_agent_rename(name: str, payload: AgentNamePayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    new_name = payload.name.strip()
    if not new_name:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "New agent name is required", "type": "invalid_payload"}},
        )
    try:
        updated = rename_agent(name, new_name)
    except Exception as exc:
        duplicate = "unique" in str(exc).lower() or "duplicate" in str(exc).lower()
        return JSONResponse(
            status_code=409 if duplicate else 500,
            content={"error": {"message": f"Agent already exists: {new_name}" if duplicate else str(exc), "type": "agent_rename_failed"}},
        )
    if not updated:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    return {"status": "saved", "agent": new_name, "previous": name}


class AgentBudgetPayload(BaseModel):
    limit_usd: float | None = None  # None = no limit (opt-out)
    action: str = "alert"  # "alert" | "block"


@app.put("/admin/agents/{name}/budget")
def admin_agent_set_budget(name: str, payload: AgentBudgetPayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    if payload.action not in ("alert", "block"):
        return JSONResponse(
            status_code=422,
            content={"error": {"message": "action must be 'alert' or 'block'", "type": "invalid_budget_action"}},
        )
    if payload.limit_usd is not None and payload.limit_usd < 0:
        return JSONResponse(
            status_code=422,
            content={"error": {"message": "limit_usd must be >= 0 or null", "type": "invalid_budget_limit"}},
        )
    try:
        updated = set_agent_budget(name, payload.limit_usd, payload.action)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "agent_budget_failed"}},
        )
    if not updated:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    return {"status": "saved", "agent": name, "limit_usd": payload.limit_usd, "action": payload.action}


@app.put("/admin/agents/{name}/aux-tasks")
def admin_agent_set_aux_tasks(name: str, request: Request):
    """Make this agent the auxiliary-tasks agent. The role is exclusive — it is
    removed from whichever agent held it before."""
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        updated = set_aux_tasks_agent(name)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "agent_aux_tasks_failed"}},
        )
    if not updated:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    return {"status": "saved", "aux_tasks_agent": name}


class AgentModelsPayload(BaseModel):
    models: list[str] = Field(default_factory=list)


@app.put("/admin/agents/{name}/models")
def admin_agent_set_models(name: str, payload: AgentModelsPayload, request: Request):
    """Associate models to the agent. Empty list removes the restriction (all models allowed)."""
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        updated = set_agent_models(name, [model.strip() for model in payload.models if model.strip()])
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "agent_models_failed"}},
        )
    if not updated:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    return {"status": "saved", "agent": name, "models": payload.models}


@app.get("/admin/agents/{name}/key")
def admin_agent_key(name: str, request: Request):
    """Reveal an agent's API key for the copy button. Requires the admin token."""
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        api_key = get_agent_api_key(name)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "agent_store_unavailable"}},
        )
    if api_key is None:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    return {"agent": name, "api_key": api_key}


@app.delete("/admin/agents/{name}")
def admin_agent_delete(name: str, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        deleted = delete_agent(name)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "agent_delete_failed"}},
        )
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Agent not found: {name}", "type": "agent_not_found"}},
        )
    return {"status": "deleted", "agent": name}


class DemandRoutesPayload(BaseModel):
    models: list[str] = Field(default_factory=list)


@app.get("/admin/demand-routes")
def admin_demand_routes(request: Request):
    # Read-only: configured chain + rank-derived default per demand class.
    try:
        routes = get_demand_routes()
    except Exception:
        routes = {}
    try:
        registry = load_registry_with_db_health()
        healthy = registry.healthy_for_capability("text")
    except Exception:
        healthy = []
    defaults = {demand: [model.id for model in default_chain(healthy, demand, performance=model_performance_cached())][:8] for demand in DEMANDS}
    return {
        "demands": list(DEMANDS),
        "info": DEMAND_INFO,
        "routes": {demand: routes.get(demand, []) for demand in DEMANDS},
        "defaults": defaults,
        "virtual_models": VIRTUAL_MODELS,
    }


@app.put("/admin/demand-routes/{demand}")
def admin_demand_routes_set(demand: str, payload: DemandRoutesPayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    if demand not in DEMANDS:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": f"Unknown demand class: {demand}", "type": "invalid_payload"}},
        )
    try:
        set_demand_routes(demand, [model.strip() for model in payload.models if model.strip()])
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "demand_routes_failed"}},
        )
    return {"status": "saved", "demand": demand, "models": payload.models}


class ContextCompactionPayload(BaseModel):
    enabled: bool


@app.get("/admin/settings/context-compaction")
def admin_context_compaction_get():
    try:
        enabled = context_compaction_enabled()
    except Exception:
        enabled = True
    return {"enabled": enabled}


@app.post("/admin/settings/context-compaction")
def admin_context_compaction_set(payload: ContextCompactionPayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        set_context_compaction_enabled(payload.enabled)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "settings_failed"}},
        )
    return {"status": "saved", "enabled": payload.enabled}


@app.get("/admin/pricing/models")
def admin_pricing_models():
    # Read-only: no secrets, just which models have a resolvable reference
    # price and where it came from — safe to load without a token.
    from app.pricing import resolve_price_info

    try:
        registry = load_registry_with_db_health()
    except Exception:
        return {"models": []}
    seen: dict[str, dict[str, Any]] = {}
    for model in registry.models:
        if model.id in seen:
            continue
        try:
            info = resolve_price_info(model.id, model.provider_model)
        except Exception:
            info = None
        seen[model.id] = {
            "public_id": model.id,
            "provider_model": model.provider_model,
            "priced": info is not None,
            "input_cost_per_token": info.get("input_cost_per_token") if info else None,
            "output_cost_per_token": info.get("output_cost_per_token") if info else None,
            "source": info.get("source") if info else None,
        }
    models = sorted(seen.values(), key=lambda item: (not item["priced"], item["public_id"]))
    try:
        last_synced = get_setting("pricing_last_synced")
    except Exception:
        last_synced = None
    return {
        "models": models,
        "priced_count": sum(1 for m in models if m["priced"]),
        "total_count": len(models),
        "last_synced": last_synced,
    }


@app.post("/admin/pricing/sync")
def admin_pricing_sync(request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    from app.pricing import sync_catalog_from_litellm, sync_provider_pricing

    try:
        catalog_entries = sync_catalog_from_litellm()
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"error": {"message": str(exc), "type": "pricing_sync_failed"}},
        )
    try:
        registry = load_registry_with_db_health()
        live_entries = sync_provider_pricing(registry)
    except Exception:
        live_entries = 0
    try:
        checked, priced = backfill_reference_costs()
    except Exception:
        checked, priced = 0, 0
    last_synced = datetime.now(timezone.utc).isoformat()
    try:
        set_setting("pricing_last_synced", last_synced)
    except Exception:
        pass
    return {
        "status": "synced",
        "catalog_entries": catalog_entries,
        "live_entries": live_entries,
        "backfill_checked": checked,
        "backfill_priced": priced,
        "last_synced": last_synced,
    }


@app.get("/admin/providers/health")
def admin_provider_health(request: Request):
    # Read-only: no secrets in the payload, so the dashboard can load without a token.
    try:
        return {"providers": latest_provider_health_rows()}
    except Exception:
        registry = load_registry()
        return {
            "providers": [
                {
                    "provider": model.provider,
                    "model_id": model.id,
                    "tier": model.tier,
                    "status": "healthy" if model.healthy else "unknown",
                    "http_code": None,
                    "latency_ms": None,
                    "error_message": "health_store_unavailable",
                    "checked_at": None,
                }
                for model in registry.models
            ]
        }


@app.get("/admin/usage")
def admin_usage(request: Request, days: int = 30, agent: str = ""):
    # Read-only: aggregated message/token/cost usage for the dashboard chart, optionally per agent.
    from app.storage import usage_summary

    try:
        return usage_summary(max(1, min(days, 365)), agent_name=agent.strip() or None)
    except Exception:
        return {"days": days, "totals": {"messages": 0, "tokens": 0, "cost": 0.0}, "daily": [], "by_model": [], "by_demand": []}


@app.get("/admin/usage/yearly")
def admin_usage_yearly(request: Request, year: int = 0):
    # Read-only: per-agent monthly totals for the current year, combining
    # archived ai_router.usage_monthly rollups with live route_events.
    from app.storage import yearly_usage_by_agent

    try:
        return yearly_usage_by_agent(year or None)
    except Exception:
        return {"year": year, "by_agent": []}


@app.get("/admin/usage/yearly-by-demand")
def admin_usage_yearly_by_demand(request: Request, year: int = 0):
    # Read-only: per-demand-class monthly totals for the current year, combining
    # archived ai_router.usage_monthly_demand rollups with live route_events.
    from app.storage import yearly_usage_by_demand

    try:
        return yearly_usage_by_demand(year or None)
    except Exception:
        return {"year": year, "by_demand": []}


@app.post("/admin/usage/archive")
def admin_usage_archive(request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        return archive_old_route_events()
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "archive_failed"}},
        )


@app.get("/admin/routes/recent")
def admin_routes_recent(request: Request, limit: int = 25, agent: str = ""):
    # Read-only: no secrets in the payload, so the dashboard can load without a token.
    try:
        safe_limit = max(1, min(limit, 100))
        return {"routes": recent_route_events(safe_limit, agent_name=agent.strip() or None)}
    except Exception:
        return {"routes": []}


@app.post("/admin/providers/rescan")
def admin_provider_rescan(request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        results = scan_registry()
        persist_health_results(results)
        try:
            # Unhealthy models leave the on/off selection; the sync below then
            # removes them from (and adds recovered ones back to) every agent.
            set_models_enabled_from_health(results)
        except Exception:
            pass  # the scan result is still valid without the selection sync
        try:
            sync_agent_model_associations()
        except Exception:
            pass  # the scan result is still valid without the agent sync
        return build_scan_payload(results)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "scan_failed"}},
        )


@app.get("/admin/providers/readiness")
def admin_provider_readiness(request: Request):
    # Read-only: reports env var names and a configured boolean only, never secret values.
    return {"providers": provider_readiness()}


def _mask_registry_providers(providers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from app.providers.plans import plan_for
    from app.ranking import intelligence_score
    from app.registry import mask_secret

    masked = []
    for provider in providers:
        item = dict(provider)
        api_key = item.pop("api_key", "") or ""
        item["api_key_set"] = bool(api_key)
        item["api_key_masked"] = mask_secret(api_key)
        item["models"] = [
            {**model, "score": intelligence_score(model["id"])}
            for model in item.get("models", [])
        ]
        # Subscription plans backed by a plan handler (Codex, Antigravity) resolve
        # their token from a local CLI login via OAuth, rather than a pasted key.
        plan = plan_for(item.get("base_url"))
        item["auth_method"] = "oauth" if (item.get("access_type") == "subscription" and plan and plan.resolve_token) else ""
        masked.append(item)
    return masked


@app.get("/admin/providers/registry")
def admin_provider_registry(request: Request):
    # Read-only: full provider/model configuration. Stored API keys are masked (first 4 chars only).
    from app.storage import db_providers_with_models

    try:
        return {"providers": _mask_registry_providers(db_providers_with_models()), "source": "database"}
    except Exception:
        from app.registry import load_provider_dicts

        return {"providers": _mask_registry_providers(load_provider_dicts()), "source": "yaml_fallback"}


class DiscoveryError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _discover_provider_models(
    provider_name: str,
    base_url: str,
    api_key: str,
    api_key_env: str,
    scan: bool,
    scan_timeout: float,
    api_format: str = "openai",
) -> dict[str, Any]:
    """Detect a provider's models, drop paid ones, catalog capabilities and (optionally) health-scan."""
    import httpx

    from app.providers.plans import plan_for
    from app.ranking import infer_capabilities, intelligence_score, is_free_model

    models: dict[str, dict[str, Any]] = {}
    excluded_paid = 0
    plan = plan_for(base_url)
    if plan and plan.discover_models:
        # Plan-specific catalog (e.g. Codex has no /models endpoint).
        for item in plan.discover_models():
            models[item["id"]] = {
                "id": item["id"],
                "score": intelligence_score(item["id"]),
                "free": None,
                "capabilities": list(item.get("capabilities") or ["text"]),
                "health": None,
            }
    else:
        headers = {}
        key = api_key or (os.environ.get(api_key_env, "") if api_key_env else "")
        if plan and plan.resolve_token:
            key = plan.resolve_token(api_key, api_key_env) or key
        if key:
            headers["Authorization"] = f"Bearer {key}"
        if api_format == "anthropic":
            # Anthropic's catalog lives at /v1/models and authenticates via x-api-key.
            from app.providers.anthropic_compatible import anthropic_messages_url

            models_url = anthropic_messages_url(base_url).replace("/messages", "/models")
            headers["anthropic-version"] = "2023-06-01"
            if key:
                headers["x-api-key"] = key
        else:
            models_url = base_url.rstrip("/") + "/models"
        try:
            response = httpx.get(models_url, headers=headers, timeout=30.0)
            body = response.json()
        except Exception as exc:
            raise DiscoveryError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code >= 400:
            message = body.get("error", {}).get("message") if isinstance(body, dict) else None
            raise DiscoveryError(message or f"http_{response.status_code}", status_code=response.status_code)
        items = body.get("data") if isinstance(body, dict) else None
        if not isinstance(items, list):
            raise DiscoveryError("Provider /models response is not OpenAI-compatible")

        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            model_id = str(item["id"])
            free = is_free_model(item, base_url)
            if free is False:
                excluded_paid += 1
                continue
            models[model_id] = {
                "id": model_id,
                "score": intelligence_score(model_id),
                "free": free,
                "capabilities": infer_capabilities(item),
                "health": None,
            }

    if scan and models:
        from concurrent.futures import ThreadPoolExecutor

        from app.registry import ProviderModel
        from app.validation.scanner import scan_model

        def scan_entry(entry: dict[str, Any]) -> None:
            model = ProviderModel(
                id=entry["id"],
                provider=provider_name or "discovery",
                provider_model=entry["id"],
                tier=0,
                capabilities=entry["capabilities"],
                enabled=True,
                healthy=False,
                base_url=base_url,
                api_key_env=api_key_env,
                api_key=api_key,
                api_format=api_format or "openai",
            )
            result = scan_model(model, timeout=scan_timeout)
            entry["health"] = {
                "status": result.status,
                "http_code": result.http_code,
                "latency_ms": result.latency_ms,
                "error": result.error_message,
            }

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(scan_entry, models.values()))

    def sort_key(model: dict[str, Any]) -> tuple:
        health = model.get("health") or {}
        healthy_first = 0 if health.get("status") == "healthy" else 1 if scan else 0
        return (healthy_first, -model["score"], model["id"])

    ranked = sorted(models.values(), key=sort_key)
    healthy_count = sum(1 for model in ranked if (model.get("health") or {}).get("status") == "healthy")
    return {"models": ranked, "total": len(ranked), "excluded_paid": excluded_paid, "healthy": healthy_count, "scanned": scan}


@app.post("/admin/providers/discover-models")
def admin_provider_discover_models(payload: DiscoverModelsPayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    base_url = payload.base_url.strip()
    api_key = payload.api_key.strip()
    api_key_env = payload.api_key_env.strip()
    api_format = payload.api_format.strip()
    if payload.provider_name:
        # Fall back to the stored provider config so the dashboard never needs the real key.
        try:
            from app.storage import db_providers_with_models

            stored = next((p for p in db_providers_with_models() if p["name"] == payload.provider_name), None)
        except Exception:
            stored = None
        if stored:
            base_url = base_url or stored["base_url"]
            api_key = api_key or stored.get("api_key", "")
            api_key_env = api_key_env or stored.get("api_key_env", "")
            api_format = api_format or stored.get("api_format", "")
    if not base_url:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "base_url is required (or an existing provider_name)", "type": "invalid_payload"}},
        )
    try:
        return _discover_provider_models(payload.provider_name, base_url, api_key, api_key_env, payload.scan, payload.scan_timeout, api_format=api_format or "openai")
    except DiscoveryError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"message": str(exc), "type": "discovery_failed"}},
        )


@app.get("/admin/providers/{name}/key")
def admin_provider_key(name: str, request: Request):
    """Reveal a provider's API key for the copy button. Requires the admin token."""
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    from app.storage import db_providers_with_models

    try:
        provider = next((p for p in db_providers_with_models() if p["name"] == name), None)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "registry_unavailable"}},
        )
    if not provider:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Provider not found: {name}", "type": "provider_not_found"}},
        )
    api_key = provider.get("api_key") or (os.environ.get(provider.get("api_key_env", ""), "") if provider.get("api_key_env") else "")
    return {"provider": name, "api_key": api_key}


class TaskMapPayload(BaseModel):
    model: str


@app.get("/admin/task-map")
def admin_task_map():
    # Read-only: Hermes task map for the dashboard. No secrets involved.
    from app.storage import get_task_map

    try:
        entries = get_task_map()
    except Exception:
        entries = []
    return {"tasks": entries}


@app.put("/admin/task-map/{task}")
def admin_task_map_set(task: str, payload: TaskMapPayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    model = payload.model.strip()
    if not model:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "model is required", "type": "invalid_payload"}},
        )
    from app.storage import set_task_map_model

    try:
        updated = set_task_map_model(task, model)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "task_map_failed"}},
        )
    if not updated:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Task not found: {task}", "type": "task_not_found"}},
        )
    return {"status": "saved", "task": task, "model": model}


@app.get("/admin/subscriptions/catalog")
def admin_subscription_catalog():
    # Read-only: known subscription providers (coding plans) for the dashboard picker.
    # Contains no secrets — only endpoints and where to find the plan token.
    from app.storage import list_subscription_catalog

    try:
        return {"catalog": list_subscription_catalog()}
    except Exception:
        return {"catalog": []}


@app.post("/admin/providers/{name}/validate")
def admin_provider_validate(name: str, request: Request):
    """Validate a stored provider's configuration: credential check + a real chat
    completion against each enabled model. Persists the health results."""
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    from app.registry import registry_from_provider_dicts
    from app.storage import db_providers_with_models
    from app.validation.scanner import scan_model

    try:
        provider = next((p for p in db_providers_with_models() if p["name"] == name), None)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "registry_unavailable"}},
        )
    if not provider:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Provider not found: {name}", "type": "provider_not_found"}},
        )
    access_type = provider.get("access_type") or "api_key"
    api_key = provider.get("api_key") or ""
    env_value = os.environ.get(provider.get("api_key_env", ""), "") if provider.get("api_key_env") else ""
    # Plans can resolve their own credential (e.g. Codex reads the local CLI login).
    from app.providers.plans import plan_for

    plan = plan_for(provider.get("base_url"))
    plan_token = plan.resolve_token(api_key, provider.get("api_key_env") or "") if plan and plan.resolve_token else ""
    credential_ok = access_type == "local" or bool(api_key) or bool(env_value) or bool(plan_token)
    models = [model for model in registry_from_provider_dicts([provider]).models if model.enabled]
    if not credential_ok:
        return {
            "provider": name,
            "access_type": access_type,
            "credential_ok": False,
            "summary": {"total": len(models), "healthy": 0, "unhealthy": len(models)},
            "results": [],
            "message": "No credential configured — paste the subscription token or API key first.",
        }
    if not models:
        return {
            "provider": name,
            "access_type": access_type,
            "credential_ok": True,
            "summary": {"total": 0, "healthy": 0, "unhealthy": 0},
            "results": [],
            "message": "No enabled models to validate — detect models or add them manually first.",
        }
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda model: scan_model(model, timeout=30.0), models))
    try:
        persist_health_results(results)
    except Exception:
        pass  # validation report still useful when the DB write fails
    payload = build_scan_payload(results)
    payload.update({"provider": name, "access_type": access_type, "credential_ok": True})
    return payload


@app.post("/admin/providers/resync")
def admin_provider_resync(request: Request):
    """Full sync: re-discover, catalog and health-scan the free models of every enabled provider."""
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    from app.storage import db_providers_with_models

    try:
        providers = db_providers_with_models()
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "registry_unavailable"}},
        )
    report: list[dict[str, Any]] = []
    for provider in providers:
        name = provider["name"]
        if not provider.get("enabled", True):
            report.append({"provider": name, "skipped": "disabled"})
            continue
        try:
            result = _discover_provider_models(
                name,
                provider["base_url"],
                provider.get("api_key", ""),
                provider.get("api_key_env", ""),
                scan=True,
                scan_timeout=20.0,
                api_format=provider.get("api_format") or "openai",
            )
        except DiscoveryError as exc:
            report.append({"provider": name, "error": str(exc)})
            continue
        if not result["models"]:
            report.append({"provider": name, "error": "no_free_models_found"})
            continue
        models_payload = []
        for model in result["models"]:
            public_id = f"{name}/{model['id']}"
            health_status = (model.get("health") or {}).get("status")
            models_payload.append(
                {
                    "id": public_id,
                    "provider_model": model["id"],
                    "capabilities": model["capabilities"],
                    # the on/off selection follows the scan verdict: unhealthy models
                    # are unchecked, recovered (and new healthy) ones come back on
                    "enabled": health_status == "healthy",
                    "health": model.get("health"),
                }
            )
        try:
            upsert_provider({**provider, "models": models_payload})
        except Exception as exc:
            report.append({"provider": name, "error": str(exc)})
            continue
        report.append(
            {
                "provider": name,
                "total": result["total"],
                "healthy": result["healthy"],
                "excluded_paid": result["excluded_paid"],
            }
        )
    try:
        sync_agent_model_associations()
    except Exception:
        pass  # the resync report is still valid without the agent sync
    return {"providers": report}


@app.put("/admin/providers/{name}")
def admin_provider_upsert(name: str, payload: ProviderPayload, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    if payload.name != name:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Path name and payload name must match", "type": "invalid_payload"}},
        )
    if not payload.models:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Provider must have at least one model", "type": "invalid_payload"}},
        )
    if payload.access_type not in ("subscription", "api_key", "local"):
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "access_type must be subscription, api_key or local", "type": "invalid_payload"}},
        )
    if payload.cost_type not in ("free", "paid"):
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "cost_type must be free or paid", "type": "invalid_payload"}},
        )
    if payload.api_format not in ("openai", "anthropic"):
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "api_format must be openai or anthropic", "type": "invalid_payload"}},
        )
    try:
        # manual=True: the enabled flags in a dashboard save are the user's
        # curation — unchecked models become manual_off (rescan/resync never
        # re-enable them; only a manual re-check does).
        upsert_provider(payload.model_dump(), manual=True)
        try:
            # Models switched off here leave every agent's list; new enabled models
            # reach the agents already participating in this provider.
            sync_agent_model_associations()
        except Exception:
            pass
        return {"status": "saved", "provider": payload.name}
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "provider_save_failed"}},
        )


@app.delete("/admin/providers/{name}")
def admin_provider_delete(name: str, request: Request):
    auth_error = require_admin(request)
    if auth_error:
        return auth_error
    try:
        deleted = delete_provider(name)
    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={"error": {"message": str(exc), "type": "provider_delete_failed"}},
        )
    if not deleted:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": f"Provider not found: {name}", "type": "provider_not_found"}},
        )
    return {"status": "deleted", "provider": name}
