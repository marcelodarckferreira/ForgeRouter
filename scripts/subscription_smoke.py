#!/usr/bin/env python
"""Operational smoke test for native subscription providers.

The script prints sanitized JSON only: it never prints bearer tokens, passwords,
cookies, or raw upstream request URLs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.registry import ProviderModel
from app.providers.deepseek_web import deepseek_web_chat_completion, deepseek_web_discover_models, deepseek_web_token
from app.providers.zai import zai_chat_completion, zai_discover_models, zai_token


def _result(status: str, **extra: Any) -> dict[str, Any]:
    return {"status": status, **extra}


def _chat_excerpt(body: Any) -> str:
    if not isinstance(body, dict):
        return str(type(body))
    if "error" in body:
        error = body.get("error") or {}
        if isinstance(error, dict):
            return str(error.get("message") or error.get("code") or error)[:300]
        return str(error)[:300]
    choices = body.get("choices") or []
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message") or {}
        if isinstance(message, dict):
            return str(message.get("content") or "")[:300]
    return ""


def smoke_zai(prompt: str, run_chat: bool) -> dict[str, Any]:
    models = zai_discover_models()
    report = {
        "provider": "subscription_zai",
        "discover": _result("ok", models=[model["id"] for model in models]),
    }
    try:
        token = zai_token()
    except Exception as exc:
        report["auth"] = _result("failed", error=f"{type(exc).__name__}: {exc}")
        return report
    if not token:
        report["auth"] = _result("missing")
        return report
    report["auth"] = _result("ok", token_shape="jwt" if token.count(".") >= 2 else "opaque")
    if not run_chat:
        return report
    model = ProviderModel(
        id="subscription_zai/glm-4.7",
        provider="subscription_zai",
        provider_model="glm-4.7",
        tier=2,
        capabilities=["text"],
        enabled=True,
        healthy=True,
        base_url="https://chat.z.ai/api",
    )
    status, body = zai_chat_completion(model, {"stream": False, "messages": [{"role": "user", "content": prompt}]})
    report["chat"] = _result("ok" if status == 200 else "failed", http_code=status, excerpt=_chat_excerpt(body))
    return report


def smoke_deepseek(prompt: str, run_chat: bool) -> dict[str, Any]:
    models = deepseek_web_discover_models()
    report = {
        "provider": "subscription_deepseek",
        "discover": _result("ok", models=[model["id"] for model in models]),
    }
    try:
        token = deepseek_web_token()
    except Exception as exc:
        report["auth"] = _result("failed", error=f"{type(exc).__name__}: {exc}")
        return report
    if not token:
        report["auth"] = _result("missing", hint="set ~/.deepseek/auth.json or DEEPSEEK_WEB_*")
        return report
    report["auth"] = _result("ok", token_shape="jwt" if token.count(".") >= 2 else "opaque")
    if not run_chat:
        return report
    model = ProviderModel(
        id="subscription_deepseek/deepseek-default",
        provider="subscription_deepseek",
        provider_model="deepseek-default",
        tier=2,
        capabilities=["text"],
        enabled=True,
        healthy=True,
        base_url="https://chat.deepseek.com/api/v0",
    )
    status, body = deepseek_web_chat_completion(model, {"stream": False, "messages": [{"role": "user", "content": prompt}]})
    report["chat"] = _result("ok" if status == 200 else "failed", http_code=status, excerpt=_chat_excerpt(body))
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke-test native ForgeRouter subscription providers")
    parser.add_argument("--provider", choices=["all", "zai", "deepseek"], default="all")
    parser.add_argument("--skip-chat", action="store_true", help="test discovery/auth only")
    parser.add_argument("--prompt", default="Reply only with OK")
    args = parser.parse_args()

    run_chat = not args.skip_chat
    reports = []
    if args.provider in ("all", "zai"):
        reports.append(smoke_zai(args.prompt, run_chat))
    if args.provider in ("all", "deepseek"):
        reports.append(smoke_deepseek(args.prompt, run_chat))

    print(json.dumps({"providers": reports}, ensure_ascii=False, indent=2))
    failed = any((item.get("chat") or item.get("auth") or {}).get("status") == "failed" for item in reports)
    missing = any((item.get("auth") or {}).get("status") == "missing" for item in reports)
    return 2 if failed else 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
