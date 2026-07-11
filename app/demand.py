from __future__ import annotations

import re
from typing import Any

from app.ranking import intelligence_score
from app.registry import ProviderModel

# Demand classes, from cheapest to deepest. Each routes to a chain of models:
# a custom chain stored in ai_router.demand_routes, or a rank-derived default.
DEMANDS = ("simple", "standard", "complex", "reasoning", "vision", "audio", "code")

DEMAND_INFO: dict[str, str] = {
    "simple": "Short utility jobs: titles, compression, quick extraction, yes/no checks.",
    "standard": "Day-to-day chat, summaries and tool calls.",
    "complex": "Coding, long context and multi-step work.",
    "reasoning": "Deep analysis and step-by-step thinking.",
    "vision": "Requests with images — routed only through vision-capable models (catalog).",
    "audio": "Audio work (TTS tag insertion, transcription post-processing) — routed only through audio-capable models (catalog).",
    "code": "Code generation and editing — routed only through code-capable models (catalog).",
}

VIRTUAL_PREFIX = "forgerouter/"
VIRTUAL_MODELS = [VIRTUAL_PREFIX + "auto", *(VIRTUAL_PREFIX + demand for demand in DEMANDS)]

REASONING_HINTS = (
    "step by step",
    "passo a passo",
    "think carefully",
    "raciocine",
    "chain of thought",
    "prove",
    "demonstre",
    "deep analysis",
    "análise profunda",
    "analise profundamente",
)

# Hints match whole words only: "prove" must not fire inside "aprove"/"provedor".
_REASONING_HINTS_RE = re.compile(r"\b(?:" + "|".join(re.escape(hint) for hint in REASONING_HINTS) + r")\b")

CODE_HINTS = (
    "refactor",
    "refatore",
    "refatorar",
    "implemente",
    "implementar",
    "escreva uma função",
    "write a function",
    "corrija o bug",
    "fix the bug",
    "stack trace",
    "traceback",
    "code review",
    "pull request",
    "teste unitário",
    "unit test",
)
_CODE_HINTS_RE = re.compile(r"\b(?:" + "|".join(re.escape(hint) for hint in CODE_HINTS) + r")\b")
_FILE_EXT_RE = re.compile(r"\b[\w./-]+\.(?:py|ts|tsx|js|jsx|java|go|rs|c|cpp|h|cs|rb|php|sql|sh|css|html|json|ya?ml|toml)\b")

# Prompt-size thresholds (chars, ~4 chars per token): keep small jobs on small models
# so the free-tier quotas of the big models survive the day.
SIMPLE_MAX_CHARS = 1_500
STANDARD_MAX_CHARS = 8_000
# Conversation history counts at a discount: task difficulty lives in the last user
# message, and weighing the full transcript made every follow-up in a long
# conversation drift to "complex". Discounted history still escalates truly long
# contexts (which need a long-context model) — just HISTORY_DISCOUNT times later.
HISTORY_DISCOUNT = 4


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _content_has_image(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(
        isinstance(part, dict) and part.get("type") in ("image_url", "input_image", "image")
        for part in content
    )


def messages_have_images(messages: list[Any]) -> bool:
    for message in messages:
        content = getattr(message, "content", None) if not isinstance(message, dict) else message.get("content")
        if _content_has_image(content):
            return True
    return False


def _looks_like_code(text: str, lowered: str) -> bool:
    if "```" in text:
        return True
    return bool(_CODE_HINTS_RE.search(lowered) or _FILE_EXT_RE.search(lowered))


def classify_request(messages: list[Any], has_tools: bool) -> str:
    """Classify a chat request into a demand class (forgerouter/auto behaviour)."""
    if messages_have_images(messages):
        return "vision"
    total_chars = 0
    last_user = ""
    for message in messages:
        role = getattr(message, "role", None) or (message.get("role") if isinstance(message, dict) else "")
        content = getattr(message, "content", None) if not isinstance(message, dict) else message.get("content")
        text = _message_text(content)
        total_chars += len(text)
        if role == "user" and text:
            last_user = text
    lowered = last_user.lower()
    effective_chars = len(last_user) + (total_chars - len(last_user)) // HISTORY_DISCOUNT
    if _looks_like_code(last_user, lowered):
        return "code"
    if _REASONING_HINTS_RE.search(lowered):
        return "reasoning"
    if has_tools:
        return "standard" if effective_chars < STANDARD_MAX_CHARS else "complex"
    if effective_chars < SIMPLE_MAX_CHARS:
        return "simple"
    if effective_chars < STANDARD_MAX_CHARS:
        return "standard"
    return "complex"


def default_chain(models: list[ProviderModel], demand: str) -> list[ProviderModel]:
    """Rank-derived chain for a demand when no custom chain is configured.

    simple: best of the small models (economy first); standard: mid band;
    complex: high rank; reasoning: reasoning-capable, highest rank first.
    """
    by_score_desc = sorted(models, key=lambda model: -intelligence_score(model.id))
    if demand in ("vision", "audio", "code"):
        # Vision/audio/code are catalog particularities: only models with the capability may serve them.
        return [model for model in by_score_desc if demand in model.capabilities]
    if demand == "reasoning":
        band = [model for model in by_score_desc if "reasoning" in model.capabilities]
        return band or by_score_desc[:3]
    if demand == "complex":
        band = [model for model in by_score_desc if intelligence_score(model.id) >= 50]
        return band or by_score_desc[:3]
    if demand == "standard":
        band = [model for model in by_score_desc if 30 <= intelligence_score(model.id) < 50]
        return band or by_score_desc
    small = [model for model in by_score_desc if intelligence_score(model.id) < 30]
    return small or list(reversed(by_score_desc))[:3]


def resolve_demand(requested_model: str, messages: list[Any], has_tools: bool) -> str | None:
    """Demand class for the request, or None when a concrete model id was requested."""
    name = (requested_model or "auto").strip()
    if name in ("auto", VIRTUAL_PREFIX + "auto"):
        return classify_request(messages, has_tools)
    if name.startswith(VIRTUAL_PREFIX):
        suffix = name[len(VIRTUAL_PREFIX):]
        if suffix in DEMANDS:
            return suffix
        return classify_request(messages, has_tools)
    return None
