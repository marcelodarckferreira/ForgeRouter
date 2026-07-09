from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.registry import ProviderModel

SILENT_FAILURE_PATTERNS = (
    "unauthorized",
    "invalid api key",
    "insufficient quota",
    "billing",
    "balance",
    "subscription",
    "limit exceeded",
    "rate limit",
    "model not found",
)


@dataclass(frozen=True)
class HealthResult:
    model_id: str
    status: str
    http_code: int | None
    latency_ms: int | None
    error_message: str | None = None


def _message_from_response(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices") or []
    if not choices:
        return {}
    return choices[0].get("message") or {}


def detect_silent_failure(response: dict[str, Any]) -> str | None:
    choices = response.get("choices") or []
    if not choices:
        return "empty_choices"

    message = _message_from_response(response)
    content = message.get("content")
    tool_calls = message.get("tool_calls")
    reasoning = message.get("reasoning") or message.get("reasoning_content")
    # Reasoning output proves the model is alive even when the content budget ran out.
    has_signs_of_life = bool(tool_calls) or (isinstance(reasoning, str) and reasoning.strip())

    if isinstance(content, str):
        lowered = content.lower()
        if any(pattern in lowered for pattern in SILENT_FAILURE_PATTERNS):
            return "quota_or_subscription"
        if not content.strip() and not has_signs_of_life:
            return "empty_content"
        return None

    if has_signs_of_life:
        return None

    return "empty_content"


def classify_health_response(
    model: ProviderModel,
    http_code: int | None,
    response: dict[str, Any] | None,
    latency_ms: int | None,
) -> HealthResult:
    if http_code != 200:
        return HealthResult(model.id, "unhealthy", http_code, latency_ms, f"http_{http_code}")
    if response is None:
        return HealthResult(model.id, "unhealthy", http_code, latency_ms, "empty_response")

    silent_failure = detect_silent_failure(response)
    if silent_failure:
        return HealthResult(model.id, "unhealthy", http_code, latency_ms, silent_failure)

    return HealthResult(model.id, "healthy", http_code, latency_ms, None)
