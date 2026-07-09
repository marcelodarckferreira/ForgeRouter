from app.validation.health import detect_silent_failure, classify_health_response
from app.registry import ProviderModel


def test_detects_empty_content_as_silent_failure():
    response = {"choices": [{"message": {"content": ""}}]}

    assert detect_silent_failure(response) == "empty_content"


def test_detects_quota_text_inside_http_200():
    response = {"choices": [{"message": {"content": "Your subscription has insufficient quota"}}]}

    assert detect_silent_failure(response) == "quota_or_subscription"


def test_accepts_non_empty_text_response():
    response = {"choices": [{"message": {"content": "OK"}}]}

    assert detect_silent_failure(response) is None


def test_classify_health_response_marks_valid_text_healthy():
    model = ProviderModel(
        id="test/model",
        provider="test",
        provider_model="model",
        tier=2,
        capabilities=["text"],
        enabled=True,
        healthy=False,
    )
    result = classify_health_response(model, 200, {"choices": [{"message": {"content": "OK"}}]}, 100)

    assert result.status == "healthy"
    assert result.latency_ms == 100
    assert result.error_message is None
