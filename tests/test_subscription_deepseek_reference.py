from fastapi.testclient import TestClient

from app.main import app
from app.providers.deepseek_web import deepseek_web_discover_models, deepseek_web_token
from app.providers.plans import plan_for

client = TestClient(app)


def test_subscription_deepseek_plan_is_native():
    plan = plan_for("https://chat.deepseek.com/api/v0")

    assert plan is not None
    assert plan.chat_completion is not None
    assert plan.discover_models is not None
    assert plan.resolve_token is not None


def test_subscription_deepseek_static_discovery_does_not_call_upstream():
    models = deepseek_web_discover_models()

    assert {model["id"] for model in models} == {"deepseek-default", "deepseek-expert", "deepseek-vision"}
    vision = next(model for model in models if model["id"] == "deepseek-vision")
    assert "vision" in vision["capabilities"]


def test_subscription_deepseek_discovery_uses_native_handler():

    response = client.post(
        "/admin/providers/discover-models",
        json={
            "provider_name": "subscription_deepseek",
            "base_url": "https://chat.deepseek.com/api/v0",
            "api_key": "",
            "scan": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert {model["id"] for model in body["models"]} == {"deepseek-default", "deepseek-expert", "deepseek-vision"}
    vision = next(model for model in body["models"] if model["id"] == "deepseek-vision")
    assert "vision" in vision["capabilities"]


def test_subscription_deepseek_token_from_inline_json():
    token = deepseek_web_token('{"token":"deepseek-web-token"}')

    assert token == "deepseek-web-token"
