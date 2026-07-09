from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

VALID_PAYLOAD = {
    "name": "cerebras",
    "tier": 2,
    "base_url": "https://api.cerebras.ai/v1",
    "api_key_env": "CEREBRAS_API_KEY",
    "enabled": True,
    "models": [
        {
            "id": "cerebras/llama3.1-8b",
            "provider_model": "llama3.1-8b",
            "capabilities": ["text"],
            "enabled": True,
            "health": {"status": "healthy", "http_code": 200, "latency_ms": 150, "error": None},
        }
    ],
}


def test_upsert_provider_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.put("/admin/providers/cerebras", json=VALID_PAYLOAD)

    assert response.status_code == 401


def test_upsert_provider_persists_payload(monkeypatch):
    saved = {}
    monkeypatch.setattr("app.main.upsert_provider", lambda payload: saved.update(payload))

    response = client.put("/admin/providers/cerebras", json=VALID_PAYLOAD)

    assert response.status_code == 200
    assert response.json() == {"status": "saved", "provider": "cerebras"}
    assert saved["name"] == "cerebras"
    assert saved["models"][0]["id"] == "cerebras/llama3.1-8b"
    assert saved["models"][0]["health"]["status"] == "healthy"


def test_upsert_provider_persists_access_and_cost(monkeypatch):
    saved = {}
    monkeypatch.setattr("app.main.upsert_provider", lambda payload: saved.update(payload))

    payload = {**VALID_PAYLOAD, "access_type": "subscription", "cost_type": "paid", "auth_config": {"extra_headers": {"X-Plan": "coding"}}}
    response = client.put("/admin/providers/cerebras", json=payload)

    assert response.status_code == 200
    assert saved["access_type"] == "subscription"
    assert saved["cost_type"] == "paid"
    assert saved["auth_config"] == {"extra_headers": {"X-Plan": "coding"}}


def test_upsert_provider_rejects_invalid_access_type(monkeypatch):

    response = client.put("/admin/providers/cerebras", json={**VALID_PAYLOAD, "access_type": "oauth"})

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_payload"


def test_subscription_catalog_is_public(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)
    monkeypatch.setattr(
        "app.storage.list_subscription_catalog",
        lambda: [{"name": "subscription_zai", "display_name": "Subscription Z.ai", "plan_hint": "GLM Coding Plan", "base_url": "https://chat.z.ai/api", "auth_method": "oauth", "token_hint": "anonymous free token or ~/.zai/auth.json", "extra_headers": {}}],
    )

    response = client.get("/admin/subscriptions/catalog")

    assert response.status_code == 200
    assert response.json()["catalog"][0]["name"] == "subscription_zai"


def test_validate_provider_scans_and_persists(monkeypatch):
    provider = {
        "name": "local-ollama",
        "tier": 4,
        "base_url": "http://127.0.0.1:11434/v1",
        "api_key_env": "",
        "api_key": "",
        "enabled": True,
        "access_type": "local",
        "cost_type": "free",
        "auth_config": {},
        "models": [{"id": "local/qwen", "provider_model": "qwen", "capabilities": ["text"], "enabled": True, "healthy": False}],
    }
    monkeypatch.setattr("app.storage.db_providers_with_models", lambda: [provider])
    from app.validation.health import HealthResult
    monkeypatch.setattr("app.validation.scanner.scan_model", lambda model, timeout=30.0: HealthResult(model.id, "healthy", 200, 120, None))
    persisted = []
    monkeypatch.setattr("app.main.persist_health_results", lambda results: persisted.extend(results))

    response = client.post("/admin/providers/local-ollama/validate")

    assert response.status_code == 200
    body = response.json()
    assert body["credential_ok"] is True
    assert body["summary"] == {"total": 1, "healthy": 1, "unhealthy": 0}
    assert [r.model_id for r in persisted] == ["local/qwen"]


def test_validate_provider_reports_missing_credential(monkeypatch):
    monkeypatch.delenv("MISSING_KEY_ENV", raising=False)
    provider = {
        "name": "subplan",
        "tier": 2,
        "base_url": "https://api.example.com/v1",
        "api_key_env": "MISSING_KEY_ENV",
        "api_key": "",
        "enabled": True,
        "access_type": "subscription",
        "cost_type": "paid",
        "auth_config": {},
        "models": [{"id": "subplan/m1", "provider_model": "m1", "capabilities": ["text"], "enabled": True, "healthy": False}],
    }
    monkeypatch.setattr("app.storage.db_providers_with_models", lambda: [provider])

    response = client.post("/admin/providers/subplan/validate")

    assert response.status_code == 200
    body = response.json()
    assert body["credential_ok"] is False
    assert "token" in body["message"]


def test_upsert_provider_rejects_name_mismatch(monkeypatch):

    response = client.put("/admin/providers/other", json=VALID_PAYLOAD)

    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_payload"


def test_upsert_provider_rejects_empty_models(monkeypatch):

    response = client.put("/admin/providers/cerebras", json={**VALID_PAYLOAD, "models": []})

    assert response.status_code == 400


def test_delete_provider_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.delete("/admin/providers/cerebras")

    assert response.status_code == 401


def test_delete_provider_returns_404_when_missing(monkeypatch):
    monkeypatch.setattr("app.main.delete_provider", lambda name: False)

    response = client.delete("/admin/providers/ghost")

    assert response.status_code == 404


def test_delete_provider_deletes(monkeypatch):
    deleted = []
    monkeypatch.setattr("app.main.delete_provider", lambda name: deleted.append(name) or True)

    response = client.delete("/admin/providers/cerebras")

    assert response.status_code == 200
    assert deleted == ["cerebras"]


def test_registry_endpoint_is_public_and_falls_back_to_yaml(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = client.get("/admin/providers/registry")

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "yaml_fallback"
    assert any(provider["name"] == "local" for provider in payload["providers"])


def test_registry_endpoint_masks_stored_api_keys(monkeypatch):
    monkeypatch.setattr(
        "app.storage.db_providers_with_models",
        lambda: [{"name": "groq", "tier": 1, "base_url": "https://api.groq.com/openai/v1", "api_key_env": "", "api_key": "gsk_supersecretvalue", "enabled": True, "models": []}],
    )

    response = client.get("/admin/providers/registry")

    assert response.status_code == 200
    provider = response.json()["providers"][0]
    assert provider["api_key_set"] is True
    assert provider["api_key_masked"] == "gsk_..."
    assert "api_key" not in provider
    assert "gsk_supersecretvalue" not in response.text


def test_discover_models_ranks_and_excludes_paid(monkeypatch):

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "data": [
                    {"id": "llama-3.2-1b", "pricing": {"prompt": "0", "completion": "0"}},
                    {"id": "llama-3.3-70b", "pricing": {"prompt": "0", "completion": "0"}},
                    {"id": "expensive-model", "pricing": {"prompt": "0.002", "completion": "0.004"}},
                ]
            }

    import httpx

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: FakeResponse())

    response = client.post("/admin/providers/discover-models", json={"base_url": "https://provider/v1", "scan": False})

    assert response.status_code == 200
    payload = response.json()
    assert [model["id"] for model in payload["models"]] == ["llama-3.3-70b", "llama-3.2-1b"]
    assert payload["models"][0]["score"] > payload["models"][1]["score"]
    assert all(model["free"] is True for model in payload["models"])
    assert payload["excluded_paid"] == 1
    assert payload["total"] == 2
    assert payload["scanned"] is False


def test_discover_models_catalogs_capabilities_and_scans(monkeypatch):

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {
                "data": [
                    {
                        "id": "vision-tools-model",
                        "pricing": {"prompt": "0", "completion": "0"},
                        "architecture": {"input_modalities": ["text", "image"], "output_modalities": ["text"]},
                        "supported_parameters": ["tools", "temperature"],
                    }
                ]
            }

    import httpx

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: FakeResponse())

    from app.validation.health import HealthResult

    monkeypatch.setattr(
        "app.validation.scanner.scan_model",
        lambda model, timeout=20.0: HealthResult(model.id, "healthy", 200, 120, None),
    )

    response = client.post("/admin/providers/discover-models", json={"base_url": "https://provider/v1"})

    assert response.status_code == 200
    payload = response.json()
    model = payload["models"][0]
    assert set(model["capabilities"]) >= {"text", "vision", "tool_call"}
    assert model["health"]["status"] == "healthy"
    assert payload["healthy"] == 1
    assert payload["scanned"] is True


def test_discover_models_requires_base_url_or_provider(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = client.post("/admin/providers/discover-models", json={})

    assert response.status_code == 400


def test_discover_models_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.post("/admin/providers/discover-models", json={"base_url": "http://provider/v1"})

    assert response.status_code == 401


def test_usage_endpoint_is_public_with_empty_fallback(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    response = client.get("/admin/usage")

    assert response.status_code == 200
    payload = response.json()
    assert payload["totals"] == {"messages": 0, "tokens": 0, "cost": 0.0}


def test_usage_endpoint_returns_summary(monkeypatch):
    summary = {
        "days": 30,
        "totals": {"messages": 4, "tokens": 900, "cost": 0.0},
        "daily": [{"day": "2026-06-10", "messages": 4, "tokens": 900, "cost": 0.0}],
        "by_model": [{"model_id": "local/qwen2.5:1.5b", "messages": 4, "tokens": 900, "cost": 0.0, "pct_total": 100.0}],
    }
    monkeypatch.setattr("app.storage.usage_summary", lambda days=30, agent_name=None: summary)

    response = client.get("/admin/usage?days=30")

    assert response.status_code == 200
    assert response.json() == summary


def test_provider_key_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.get("/admin/providers/groq/key")

    assert response.status_code == 401


def test_provider_key_returns_stored_key_with_token(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)
    monkeypatch.setattr(
        "app.storage.db_providers_with_models",
        lambda: [{"name": "groq", "tier": 1, "base_url": "https://x/v1", "api_key_env": "", "api_key": "gsk_fullsecret", "enabled": True, "models": []}],
    )

    response = client.get("/admin/providers/groq/key", headers={"Authorization": "Bearer secret"})

    assert response.status_code == 200
    assert response.json() == {"provider": "groq", "api_key": "gsk_fullsecret"}


def test_resync_requires_token_when_configured(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "secret" else None)

    response = client.post("/admin/providers/resync")

    assert response.status_code == 401


def test_resync_rediscovers_and_saves_every_enabled_provider(monkeypatch):
    monkeypatch.setattr(
        "app.storage.db_providers_with_models",
        lambda: [
            {
                "name": "groq", "tier": 1, "base_url": "https://api.groq.com/openai/v1",
                "api_key_env": "", "api_key": "gsk_x", "enabled": True,
                "models": [{"id": "groq/llama-3.1-8b-instant", "provider_model": "llama-3.1-8b-instant", "capabilities": ["text"], "enabled": False, "healthy": True}],
            },
            {"name": "off", "tier": 5, "base_url": "https://off/v1", "api_key_env": "", "api_key": "", "enabled": False, "models": []},
        ],
    )

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"data": [{"id": "llama-3.1-8b-instant"}, {"id": "new-model-9b"}]}

    import httpx

    monkeypatch.setattr(httpx, "get", lambda *args, **kwargs: FakeResponse())

    from app.validation.health import HealthResult

    monkeypatch.setattr(
        "app.validation.scanner.scan_model",
        lambda model, timeout=20.0: HealthResult(model.id, "healthy", 200, 100, None),
    )

    saved = []
    monkeypatch.setattr("app.main.upsert_provider", lambda payload: saved.append(payload))

    response = client.post("/admin/providers/resync")

    assert response.status_code == 200
    report = response.json()["providers"]
    assert {"provider": "off", "skipped": "disabled"} in report
    groq_report = next(item for item in report if item["provider"] == "groq")
    assert groq_report["total"] == 2 and groq_report["healthy"] == 2
    assert len(saved) == 1
    models = {model["id"]: model for model in saved[0]["models"]}
    # the on/off selection follows the scan verdict: the previously unchecked model
    # scanned healthy, so it comes back on alongside the newly discovered one
    assert models["groq/llama-3.1-8b-instant"]["enabled"] is True
    assert models["groq/new-model-9b"]["enabled"] is True
    assert models["groq/new-model-9b"]["health"]["status"] == "healthy"
