"""Lossless context compaction.

Strips whitespace formatting that carries no information for the model
(trailing spaces, runs of blank lines, pretty-printing in tool-result JSON)
before a chat payload is forwarded to a provider. Nothing semantic is removed
— the model sees the same content, just without incidental formatting bytes.

Token counts are estimated with tiktoken's cl100k_base encoding purely as a
common yardstick for the "tokens saved" dashboard indicator, independent of
which provider/tokenizer actually serves the request. If the encoding can't be
loaded (e.g. no network on first use), counting is skipped — this must never
break routing.
"""

from __future__ import annotations

import json
import re
from typing import Any

_TRAILING_WS = re.compile(r"[ \t]+\n")
_BLANK_LINES = re.compile(r"\n{3,}")

_encoding: Any = None
_encoding_failed = False


def _get_encoding() -> Any:
    global _encoding, _encoding_failed
    if _encoding is None and not _encoding_failed:
        try:
            import tiktoken

            _encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            _encoding_failed = True
    return _encoding


def count_tokens(messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None) -> int | None:
    encoding = _get_encoding()
    if encoding is None:
        return None
    text = json.dumps(messages, ensure_ascii=False)
    if tools:
        text += json.dumps(tools, ensure_ascii=False)
    return len(encoding.encode(text))


def _compact_text(text: str) -> str:
    text = _TRAILING_WS.sub("\n", text)
    return _BLANK_LINES.sub("\n\n", text)


def _compact_json_if_valid(text: str) -> str:
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return text
    try:
        parsed = json.loads(stripped)
    except Exception:
        return text
    return json.dumps(parsed, separators=(",", ":"), ensure_ascii=False)


def normalize_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = []
    for message in messages:
        item = dict(message)
        content = item.get("content")
        if isinstance(content, str):
            if item.get("role") == "tool":
                # Tool results are data payloads — pretty-printing is incidental.
                compacted = _compact_json_if_valid(content)
                item["content"] = compacted if compacted != content else _compact_text(content)
            else:
                item["content"] = _compact_text(content)
        elif isinstance(content, list):
            item["content"] = [
                {**part, "text": _compact_text(part["text"])}
                if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str)
                else part
                for part in content
            ]
        normalized.append(item)
    return normalized
