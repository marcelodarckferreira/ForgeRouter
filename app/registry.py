from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.pricing import context_window


@dataclass(frozen=True)
class ProviderModel:
    id: str
    provider: str
    provider_model: str
    tier: int
    capabilities: list[str]
    enabled: bool
    healthy: bool
    base_url: str = ""
    api_key_env: str = ""
    api_key: str = ""
    extra_headers: dict[str, str] = field(default_factory=dict)
    # Wire protocol of the provider endpoint: "openai" (/chat/completions)
    # or "anthropic" (Messages API /v1/messages).
    api_format: str = "openai"
    # True = the model was unchecked by hand (permanent until re-enabled by
    # hand); False + disabled = auto-off by a health verdict (revivable).
    manual_off: bool = False


def mask_secret(value: str) -> str:
    if not value:
        return ""
    return value[:4] + "..."


# What build_chat_payload (app/providers/openai_compatible.py) actually forwards
# for a given model — not a claim about what the upstream provider itself
# accepts. ForgeRouter does not yet strip provider-incompatible params (unlike
# e.g. Mistral rejecting explicit nulls, handled separately via exclude_none),
# so this stays honest about current behavior rather than asserting per-provider
# quirks nobody has verified against the live endpoint.
_BASE_SUPPORTED_PARAMETERS = ["temperature", "max_tokens", "stream"]


def supported_parameters(model: ProviderModel) -> list[str]:
    params = list(_BASE_SUPPORTED_PARAMETERS)
    if "tool_call" in model.capabilities:
        params.append("tools")
    return params


@dataclass(frozen=True)
class ProviderRegistry:
    models: list[ProviderModel]

    def openai_models(self) -> list[dict[str, Any]]:
        entries = []
        for model in self.models:
            if not model.enabled:
                continue
            entry = {
                "id": model.id,
                "object": "model",
                "owned_by": model.provider,
                "metadata": {
                    "tier": model.tier,
                    "capabilities": model.capabilities,
                    "healthy": model.healthy,
                    "supported_parameters": supported_parameters(model),
                },
            }
            # Real per-model window, when the LiteLLM catalog has it — never
            # guessed (see app.pricing philosophy), so the key is simply
            # omitted rather than published as an artificial value.
            window = context_window(model.id, model.provider_model)
            if window:
                entry["context_length"] = window
            entries.append(entry)
        return entries

    def healthy_for_capability(self, capability: str) -> list[ProviderModel]:
        # Fallback order = the Manage Models table: tier ascending (lower routes
        # first), AI rank descending breaks ties inside the same tier.
        from app.ranking import intelligence_score

        return [
            model
            for model in sorted(self.models, key=lambda item: (item.tier, -intelligence_score(item.id)))
            if model.enabled and model.healthy and capability in model.capabilities
        ]


def load_registry(path: str | Path = "config/providers.yaml") -> ProviderRegistry:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    models: list[ProviderModel] = []
    for provider in data.get("providers", []):
        if not provider.get("enabled", True):
            continue
        provider_name = provider["name"]
        tier = int(provider["tier"])
        for model in provider.get("models", []):
            models.append(
                ProviderModel(
                    id=model["id"],
                    provider=provider_name,
                    provider_model=model.get("provider_model", model["id"]),
                    tier=tier,
                    capabilities=list(model.get("capabilities", ["text"])),
                    enabled=bool(model.get("enabled", True)),
                    healthy=bool(model.get("healthy", False)),
                    base_url=provider.get("base_url", ""),
                    api_key_env=provider.get("api_key_env") or "",
                    api_format=provider.get("api_format") or "openai",
                    # No flag stored (YAML): a disabled model counts as manual.
                    manual_off=bool(model.get("manual_off", not model.get("enabled", True))),
                )
            )
    return ProviderRegistry(models=models)


def registry_from_provider_dicts(providers: list[dict[str, Any]]) -> ProviderRegistry:
    models: list[ProviderModel] = []
    for provider in providers:
        if not provider.get("enabled", True):
            continue
        for model in provider.get("models", []):
            models.append(
                ProviderModel(
                    id=model["id"],
                    provider=provider["name"],
                    provider_model=model.get("provider_model") or model["id"],
                    tier=int(provider["tier"]),
                    capabilities=list(model.get("capabilities", ["text"])),
                    enabled=bool(model.get("enabled", True)),
                    healthy=bool(model.get("healthy", False)),
                    base_url=provider.get("base_url", ""),
                    api_key_env=provider.get("api_key_env") or "",
                    api_key=provider.get("api_key") or "",
                    extra_headers=dict((provider.get("auth_config") or {}).get("extra_headers") or {}),
                    api_format=provider.get("api_format") or "openai",
                    manual_off=bool(model.get("manual_off", not model.get("enabled", True))),
                )
            )
    return ProviderRegistry(models=models)


def load_provider_dicts(path: str | Path = "config/providers.yaml") -> list[dict[str, Any]]:
    """Registry source of truth: the database; config/providers.yaml is the fallback."""
    try:
        from app.storage import db_providers_with_models
        providers = db_providers_with_models()
        if providers:
            return providers
    except Exception:
        pass
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return data.get("providers", [])


def load_registry_with_db_health(path: str | Path = "config/providers.yaml") -> ProviderRegistry:
    registry = registry_from_provider_dicts(load_provider_dicts(path))
    try:
        from app.storage import latest_health_by_model
        latest = latest_health_by_model()
    except Exception:
        return registry

    return ProviderRegistry(
        models=[
            ProviderModel(
                id=model.id,
                provider=model.provider,
                provider_model=model.provider_model,
                tier=model.tier,
                capabilities=model.capabilities,
                enabled=model.enabled,
                healthy=(latest.get(model.id) == "healthy") if model.id in latest else model.healthy,
                base_url=model.base_url,
                api_key_env=model.api_key_env,
                api_key=model.api_key,
                extra_headers=model.extra_headers,
                api_format=model.api_format,
                manual_off=model.manual_off,
            )
            for model in registry.models
        ]
    )


def provider_readiness(path: str | Path = "config/providers.yaml") -> list[dict[str, Any]]:
    import os
    from app.providers.plans import plan_for

    items: list[dict[str, Any]] = []
    for provider in load_provider_dicts(path):
        api_key_env = provider.get("api_key_env") or ""
        api_key = provider.get("api_key") or ""
        access_type = provider.get("access_type") or "api_key"
        env_value = os.environ.get(api_key_env, "") if api_key_env else ""
        plan = plan_for(provider.get("base_url", ""))
        plan_token = plan.resolve_token(api_key, api_key_env) if plan and plan.resolve_token else ""
        if api_key:
            source, masked = "stored", mask_secret(api_key)
        elif plan_token:
            source, masked = "oauth_file", mask_secret(plan_token)
        elif env_value:
            source, masked = "env", mask_secret(env_value)
        else:
            source, masked = "none", ""
        # Local providers never need a credential; subscription providers accept a
        # pasted token, env var, or plan-specific local OAuth/session token.
        if access_type == "local":
            key_required, key_configured = False, True
        elif access_type == "subscription":
            key_required, key_configured = True, bool(api_key) or bool(env_value) or bool(plan_token)
        else:
            key_required = bool(api_key_env) or bool(api_key)
            key_configured = bool(api_key) or bool(env_value) or bool(plan_token) if (api_key_env or api_key or plan_token) else True
        items.append({
            "provider": provider["name"],
            "tier": int(provider["tier"]),
            "enabled": bool(provider.get("enabled", True)),
            "base_url": provider.get("base_url", ""),
            "access_type": access_type,
            "cost_type": provider.get("cost_type") or "free",
            "api_format": provider.get("api_format") or "openai",
            "api_key_env": api_key_env,
            "api_key_required": key_required,
            "api_key_configured": key_configured,
            "api_key_source": source,
            "api_key_masked": masked,
            "models": [model["id"] for model in provider.get("models", []) if model.get("enabled", True)],
        })
    return items
