import json

from app.providers import zai as zai_module
from app.providers.openai_compatible import headers_for_model
from app.providers.plans import plan_for
from app.providers.zai import is_zai_base_url, zai_token
from app.registry import ProviderModel, provider_readiness


def test_plan_dispatch_matches_zai_base_url():
    plan = plan_for("https://chat.z.ai/api")
    assert plan is not None and plan.name == "zai-oauth"
    assert plan.chat_completion is not None
    assert plan.discover_models is not None
    assert plan.resolve_token is not None
    assert is_zai_base_url("https://chat.z.ai/api")


def test_zai_token_falls_back_to_oauth_file(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"tokens": {"access_token": "tok-from-oauth"}}))
    monkeypatch.setattr(zai_module, "ZAI_AUTH_FILE", str(auth))
    assert zai_token("stored", "") == "stored"
    assert zai_token("", "") == "tok-from-oauth"


def test_openai_compatible_headers_use_zai_oauth_file(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"access_token": "tok-zai"}))
    monkeypatch.setattr(zai_module, "ZAI_AUTH_FILE", str(auth))
    model = ProviderModel(
        id="subscription_zai/glm",
        provider="subscription_zai",
        provider_model="glm",
        tier=1,
        capabilities=["text"],
        enabled=True,
        healthy=True,
        base_url="https://chat.z.ai/api",
    )
    assert headers_for_model(model)["Authorization"] == "Bearer tok-zai"


class _FakeUpstream:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines
        self.closed = False

    def iter_lines(self):
        return iter(self._lines)

    def close(self):
        self.closed = True


class _FakeClient:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


def test_zai_stream_error_becomes_in_band_error_chunk(monkeypatch):
    upstream = _FakeUpstream(
        [
            'data: {"data": {"delta_content": "par"}}',
            'data: {"data": {"error": {"detail": "quota exceeded", "code": 1113}}}',
        ]
    )
    client = _FakeClient()
    model = ProviderModel(
        id="subscription_zai/glm-4.7",
        provider="subscription_zai",
        provider_model="glm-4.7",
        tier=1,
        capabilities=["text"],
        enabled=True,
        healthy=True,
        base_url="https://chat.z.ai/api",
    )
    monkeypatch.setattr(zai_module, "zai_token", lambda *args, **kwargs: "tok")
    monkeypatch.setattr(zai_module, "_upstream_request", lambda model, payload, token: (client, upstream, "glm-4.7"))

    status, body = zai_module.zai_chat_completion(model, {"stream": True, "messages": [{"role": "user", "content": "oi"}]})
    chunks = list(body)

    assert status == 200
    payloads = [json.loads(chunk.decode()[len("data: "):]) for chunk in chunks]
    assert payloads[0]["choices"][0]["delta"]["content"] == "par"
    assert "quota exceeded" in payloads[-1]["error"]["message"]
    assert payloads[-1]["error"]["code"] == "zai_upstream_error"
    # The router must classify this chunk as a provider failure, not a clean stop.
    from app.main import _error_from_sse_line

    assert _error_from_sse_line(chunks[-1].strip()) is not None
    assert upstream.closed and client.closed


def test_provider_readiness_accepts_zai_oauth_file(tmp_path, monkeypatch):
    auth = tmp_path / "auth.json"
    auth.write_text(json.dumps({"access_token": "tok-zai"}))
    monkeypatch.setattr(zai_module, "ZAI_AUTH_FILE", str(auth))
    monkeypatch.setattr(
        "app.registry.load_provider_dicts",
        lambda path="config/providers.yaml": [
            {
                "name": "subscription_zai",
                "tier": 1,
                "base_url": "https://chat.z.ai/api",
                "access_type": "subscription",
                "api_key": "",
                "api_key_env": "",
                "enabled": True,
                "models": [],
            }
        ],
    )

    item = provider_readiness()[0]
    assert item["api_key_configured"] is True
    assert item["api_key_source"] == "oauth_file"
