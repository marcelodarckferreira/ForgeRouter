"""Best-effort rescue for models that emit a tool call as plain text instead
of the provider's structured tool_calls field — common on smaller free-tier
models that don't reliably support native function calling.

Only touches the response when the caller actually requested tools, the model
didn't already return structured tool_calls, and the extracted call names a
tool that was actually offered — that last gate is what keeps this from
turning an ordinary text answer that happens to contain JSON into a spurious
tool call.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def _known_tool_names(tools: list[dict[str, Any]]) -> set[str]:
    names: set[str] = set()
    for tool in tools:
        function = tool.get("function") if isinstance(tool, dict) else None
        name = function.get("name") if isinstance(function, dict) else None
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _candidate_json_texts(content: str) -> list[str]:
    # Try fenced blocks first (most common wrapping for a "rescued" model),
    # then the raw content in case the whole message is just the JSON object.
    return [*_FENCE_RE.findall(content), content.strip()]


def _as_call(obj: Any, known_names: set[str]) -> tuple[str, Any] | None:
    if not isinstance(obj, dict):
        return None
    function = obj.get("function") if isinstance(obj.get("function"), dict) else obj
    name = function.get("name")
    if not isinstance(name, str) or name not in known_names:
        return None
    arguments = function.get("arguments", function.get("parameters", {}))
    return name, arguments


def _extract_calls(parsed: Any, known_names: set[str]) -> list[tuple[str, Any]] | None:
    if isinstance(parsed, list):
        calls = [call for item in parsed if (call := _as_call(item, known_names))]
        return calls or None
    if isinstance(parsed, dict) and isinstance(parsed.get("tool_calls"), list):
        calls = [call for item in parsed["tool_calls"] if (call := _as_call(item, known_names))]
        return calls or None
    call = _as_call(parsed, known_names)
    return [call] if call else None


def rescue_tool_calls(body: dict[str, Any], tools: list[dict[str, Any]] | None) -> bool:
    """Mutates `body` in place when a plain-text tool call is found in its
    first choice. Returns whether a rescue happened."""
    if not tools:
        return False
    known_names = _known_tool_names(tools)
    if not known_names:
        return False
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        return False
    message = choices[0].get("message")
    if not isinstance(message, dict) or message.get("tool_calls"):
        return False  # no message, or already structured — nothing to rescue
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        return False
    calls: list[tuple[str, Any]] | None = None
    for candidate in _candidate_json_texts(content):
        if not candidate:
            continue
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        calls = _extract_calls(parsed, known_names)
        if calls:
            break
    if not calls:
        return False
    message["tool_calls"] = [
        {
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": arguments if isinstance(arguments, str) else json.dumps(arguments),
            },
        }
        for name, arguments in calls
    ]
    message["content"] = None
    choices[0]["finish_reason"] = "tool_calls"
    return True
