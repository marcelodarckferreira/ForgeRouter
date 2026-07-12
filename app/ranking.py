from __future__ import annotations

import re
from typing import Any

# Curated intelligence scores (0-100), loosely following public benchmark indexes
# (Artificial Analysis-style). Patterns are matched in order against the model id;
# first hit wins. Update this table as new model families appear.
MODEL_FAMILY_SCORES: list[tuple[str, int]] = [
    # Claude Code (Anthropic Messages API via Claude Pro/Max OAuth).
    ("claude-opus-4-8", 75),
    ("claude-sonnet-4-6", 65),
    ("claude-sonnet-4-5", 60),
    ("claude-haiku-4-5", 40),
    # Gemini (Antigravity / Code Assist) — lite variants must precede their
    # non-lite siblings since "first hit wins" and the lite ids are substrings.
    ("gemini-3-pro", 68),
    ("gemini-3.1-flash-lite", 30),
    ("gemini-3-flash", 54),
    ("gemini-2.5-flash-lite", 28),
    ("gemini-2.5-pro", 62),
    ("gemini-2.5-flash", 45),
    ("glm-5", 66),
    ("gpt-oss-120b", 61),
    ("gpt-oss:120b", 61),
    ("minimax-m3", 61),
    ("deepseek-r1", 60),
    ("nemotron-3-ultra", 60),
    ("qwq", 58),
    ("kimi-k2", 57),
    ("glm-4.5", 56),
    ("nemotron-3-super", 55),
    ("deepseek-v3", 53),
    ("deepseek", 50),
    ("llama-4-maverick", 51),
    ("gpt-oss-20b", 49),
    ("gpt-oss:20b", 49),
    ("minimax", 50),
    ("nemotron", 45),
    ("llama-4-scout", 43),
    ("llama-3.1-405b", 43),
    ("llama-3.3-70b", 41),
    ("qwen-2.5-72b", 40),
    ("qwen2.5-72b", 40),
    ("qwen2.5:72b", 40),
    ("phi-4", 40),
    ("mistral-large", 38),
    ("gemma-3-27b", 38),
    ("llama-3.1-70b", 38),
    ("qwen-2.5-32b", 37),
    ("qwen2.5-32b", 37),
    ("mistral-medium", 36),
    ("mistral-small", 33),
    ("llama-3.2-90b", 33),
    ("qwen-2.5-14b", 32),
    ("qwen2.5-14b", 32),
    ("mixtral-8x22b", 30),
    ("llama-3.2-11b", 28),
    ("llama-3.1-8b", 27),
    ("qwen-2.5-7b", 27),
    ("qwen2.5-7b", 27),
    ("qwen2.5:7b", 27),
    ("ministral", 25),
    ("phi-3", 25),
    ("mixtral-8x7b", 24),
    ("gemma2-9b", 22),
    ("llama-3.2-3b", 18),
    ("gemma", 18),
    ("llama-3.2-1b", 12),
    ("llama3.2:1b", 12),
    ("qwen-2.5-1.5b", 12),
    ("qwen2.5:1.5b", 12),
    ("qwen2.5-1.5b", 12),
    ("qwen-2.5-0.5b", 8),
    ("qwen2.5:0.5b", 8),
    ("qwen2.5-0.5b", 8),
]

_PARAM_SIZE = re.compile(r"(\d+(?:\.\d+)?)b\b")


def intelligence_score(model_id: str) -> int:
    lowered = model_id.lower()
    for pattern, score in MODEL_FAMILY_SCORES:
        if pattern in lowered:
            return score
    match = _PARAM_SIZE.search(lowered)
    if match:
        size = float(match.group(1))
        for limit, score in ((1, 10), (2, 13), (4, 18), (8, 25), (15, 30), (35, 36), (75, 40)):
            if size <= limit:
                return score
        return 45
    return 20


def dynamic_score(model_id: str, performance: dict[str, dict[str, Any]] | None = None) -> float:
    """Static intelligence score blended with the model's recent behaviour.

    Success rate (route_events, last days) scales the score between 60% and
    100%; scan latency shaves up to 2 points as a near-tie breaker. Models with
    fewer than 5 recent attempts keep the static score — no penalty on thin data.
    """
    base = float(intelligence_score(model_id))
    stats = (performance or {}).get(model_id)
    if not stats or (stats.get("total") or 0) < 5:
        return base
    success_rate = min(1.0, max(0.0, float(stats.get("success_rate", 1.0))))
    latency_ms = stats.get("latency_ms") or 0
    latency_penalty = min(2.0, latency_ms / 5000.0)
    return base * (0.6 + 0.4 * success_rate) - latency_penalty


LOCAL_HOST_MARKERS = ("127.0.0.1", "localhost", "host.docker.internal")


def _pricing_is_free(pricing: dict[str, Any]) -> bool:
    for value in pricing.values():
        try:
            if float(value) > 0:
                return False
        except (TypeError, ValueError):
            continue
    return True


REASONING_MARKERS = ("reasoning", "thinking", "-r1", "qwq", "deepseek-r", "qwen3", "gpt-oss", "o3-", "o4-", "glm-4.5", "glm-4.6", "glm-5", "claude-opus", "claude-sonnet")
CODE_MARKERS = ("coder", "-code", "codestral", "starcoder", "codellama")
VISION_MARKERS = ("vision", "-vl", ":vl", "omni", "llama-4-scout", "llama-4-maverick", "pixtral", "gemma-3", "claude-")
EMBEDDING_MARKERS = ("embed",)
# Model families known to handle OpenAI tool calling even when the provider's
# /models response carries no metadata (groq, mistral, nvidia, local Ollama…).
TOOL_CALL_MARKERS = (
    "llama-3.1", "llama-3.3", "llama-4", "gpt-oss", "qwen2.5", "qwen3", "kimi",
    "mistral-", "ministral", "magistral", "devstral", "codestral", "mixtral",
    "deepseek", "glm-4", "glm-5", "gemini", "command-", "hermes", "nemotron", "compound",
    "claude-",
)


def infer_capabilities(item: dict[str, Any]) -> list[str]:
    """Catalog a model from provider metadata (OpenRouter-style) plus name heuristics."""
    model_id = str(item.get("id", "")).lower()
    caps: set[str] = {"text"}

    architecture = item.get("architecture") or {}
    inputs = [str(value).lower() for value in architecture.get("input_modalities") or []]
    outputs = [str(value).lower() for value in architecture.get("output_modalities") or []]
    modality = str(architecture.get("modality") or "").lower()
    supported = [str(value).lower() for value in item.get("supported_parameters") or []]

    if "image" in inputs or modality.split("->")[0].find("image") >= 0:
        caps.add("vision")
    if "audio" in inputs:
        caps.add("audio")
    if "embedding" in outputs or any(marker in model_id for marker in EMBEDDING_MARKERS):
        caps.add("embedding")
    if "tools" in supported or "tool_choice" in supported or any(marker in model_id for marker in TOOL_CALL_MARKERS):
        caps.add("tool_call")
    if "reasoning" in supported or "include_reasoning" in supported or any(marker in model_id for marker in REASONING_MARKERS):
        caps.add("reasoning")
    if any(marker in model_id for marker in CODE_MARKERS):
        caps.add("code")
    if any(marker in model_id for marker in VISION_MARKERS):
        caps.add("vision")
    return sorted(caps)


def is_free_model(item: dict[str, Any], base_url: str) -> bool | None:
    """True = free, False = paid, None = the provider does not publish pricing."""
    model_id = str(item.get("id", ""))
    if any(marker in base_url for marker in LOCAL_HOST_MARKERS):
        return True
    if model_id.endswith(":free"):
        return True
    pricing = item.get("pricing")
    if isinstance(pricing, dict) and pricing:
        return _pricing_is_free(pricing)
    return None
