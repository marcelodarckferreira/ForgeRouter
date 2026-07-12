from __future__ import annotations

import argparse
import json
import time
from typing import Iterable

import httpx

from app.registry import ProviderModel
from app.validation.health import HealthResult, classify_health_response


def build_scan_payload(results: Iterable[HealthResult]) -> dict:
    items = [
        {
            "model_id": result.model_id,
            "status": result.status,
            "http_code": result.http_code,
            "latency_ms": result.latency_ms,
            "error_message": result.error_message,
        }
        for result in results
    ]
    return {
        "summary": {
            "total": len(items),
            "healthy": sum(1 for item in items if item["status"] == "healthy"),
            "unhealthy": sum(1 for item in items if item["status"] != "healthy"),
        },
        "results": items,
    }


def scan_model(model: ProviderModel, timeout: float = 60.0) -> HealthResult:
    from app.providers.openai_compatible import headers_for_model
    from app.providers.plans import plan_for

    url_base = model.base_url
    url = url_base.rstrip("/") + "/chat/completions"
    payload = {
        "model": model.provider_model,
        "messages": [{"role": "user", "content": "Reply only OK"}],
        "temperature": 0,
        # Reasoning models (gpt-oss, qwen3…) burn the whole budget thinking before
        # emitting content; 8 tokens made them look like empty_content failures.
        "max_tokens": 128,
    }
    started = time.perf_counter()
    plan = plan_for(url_base)
    handler = plan.chat_completion if plan and plan.chat_completion else None
    if handler is None and getattr(model, "api_format", "openai") == "anthropic":
        from app.providers.anthropic_compatible import anthropic_chat_completion

        handler = anthropic_chat_completion
    if handler:
        # Non-default protocol (plan handler or Anthropic Messages API): the
        # handler does the real call and returns a chat-completions-shaped body
        # to classify.
        try:
            status_code, body = handler(model, payload, timeout=timeout)
            latency_ms = int((time.perf_counter() - started) * 1000)
            return classify_health_response(model, status_code, body if isinstance(body, dict) else None, latency_ms)
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return HealthResult(model.id, "unhealthy", None, latency_ms, type(exc).__name__)
    try:
        response = httpx.post(url, headers=headers_for_model(model), json=payload, timeout=timeout)
        latency_ms = int((time.perf_counter() - started) * 1000)
        try:
            body = response.json()
        except Exception:
            body = None
        return classify_health_response(model, response.status_code, body, latency_ms)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return HealthResult(model.id, "unhealthy", None, latency_ms, type(exc).__name__)


def scan_registry(path: str = "config/providers.yaml") -> list[HealthResult]:
    from concurrent.futures import ThreadPoolExecutor

    from app.registry import load_provider_dicts, registry_from_provider_dicts

    registry = registry_from_provider_dicts(load_provider_dicts(path))
    # Manually-disabled models are skipped (deliberate curation — scanning them
    # wastes free-tier rate limits). Models auto-disabled by a health verdict
    # keep being scanned, so they come back on as soon as they recover.
    models = [model for model in registry.models if model.enabled or not model.manual_off]
    if not models:
        return []
    with ThreadPoolExecutor(max_workers=8) as executor:
        return list(executor.map(lambda model: scan_model(model, timeout=30.0), models))


def main() -> int:
    parser = argparse.ArgumentParser(description="ProxyRouter provider health scanner")
    parser.add_argument("--config", default="config/providers.yaml")
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()
    results = scan_registry(args.config)
    if args.persist:
        from app.storage import persist_health_results
        persist_health_results(results)
    payload = build_scan_payload(results)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["summary"]["healthy"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
