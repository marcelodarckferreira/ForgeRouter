"""Subscription plan handlers — one per plan, each owning its particularities.

Most coding plans (Z.ai, Moonshot, MiniMax, Ollama Cloud) expose OpenAI-compatible
endpoints and need nothing beyond a pasted token, so they have no handler and take
the default chat-completions path. Plans with a different protocol, token source or
model discovery register a PlanHandler here; the router, scanner, discovery and
credential check all dispatch through plan_for(base_url).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class PlanHandler:
    name: str
    matches: Callable[[str], bool]
    # (model, chat_payload, timeout) -> (status, body|chunk-iterator); None = default OpenAI-compatible path
    chat_completion: Callable[..., tuple[int, Any]] | None = None
    # () -> [{"id", "capabilities"}] for backends without an OpenAI /models endpoint
    discover_models: Callable[[], list[dict[str, Any]]] | None = None
    # (api_key, api_key_env) -> token; covers plans whose token can be found locally
    resolve_token: Callable[[str, str], str] | None = None


def _codex_handler() -> PlanHandler:
    from app.providers.codex import codex_chat_completion, codex_discover_models, codex_token, is_codex_base_url

    return PlanHandler(
        name="openai-codex",
        matches=is_codex_base_url,
        chat_completion=codex_chat_completion,
        discover_models=codex_discover_models,
        resolve_token=codex_token,
    )


def _antigravity_handler() -> PlanHandler:
    from app.providers.antigravity import (
        antigravity_chat_completion,
        antigravity_discover_models,
        antigravity_token,
        is_antigravity_base_url,
    )

    return PlanHandler(
        name="google-antigravity",
        matches=is_antigravity_base_url,
        chat_completion=antigravity_chat_completion,
        discover_models=antigravity_discover_models,
        resolve_token=antigravity_token,
    )


def _claude_code_handler() -> PlanHandler:
    from app.providers.claude_code import (
        claude_code_chat_completion,
        claude_code_discover_models,
        claude_code_token,
        is_claude_code_base_url,
    )

    return PlanHandler(
        name="claude-code",
        matches=is_claude_code_base_url,
        chat_completion=claude_code_chat_completion,
        discover_models=claude_code_discover_models,
        resolve_token=claude_code_token,
    )


def _zai_handler() -> PlanHandler:
    from app.providers.zai import is_zai_base_url, zai_chat_completion, zai_discover_models, zai_token

    return PlanHandler(
        name="zai-oauth",
        matches=is_zai_base_url,
        chat_completion=zai_chat_completion,
        discover_models=zai_discover_models,
        resolve_token=zai_token,
    )


def _deepseek_web_handler() -> PlanHandler:
    from app.providers.deepseek_web import (
        deepseek_web_chat_completion,
        deepseek_web_discover_models,
        deepseek_web_token,
        is_deepseek_web_base_url,
    )

    return PlanHandler(
        name="subscription-deepseek",
        matches=is_deepseek_web_base_url,
        chat_completion=deepseek_web_chat_completion,
        discover_models=deepseek_web_discover_models,
        resolve_token=deepseek_web_token,
    )


PLANS: tuple[PlanHandler, ...] = (_codex_handler(), _antigravity_handler(), _claude_code_handler(), _zai_handler(), _deepseek_web_handler())


def plan_for(base_url: str | None) -> PlanHandler | None:
    for plan in PLANS:
        if plan.matches(base_url or ""):
            return plan
    return None
