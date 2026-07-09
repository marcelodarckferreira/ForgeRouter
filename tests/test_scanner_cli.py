from app.validation.scanner import build_scan_payload
from app.validation.health import HealthResult


def test_build_scan_payload_serializes_health_results():
    payload = build_scan_payload([HealthResult("mistral/mistral-small-latest", "unhealthy", 401, 120, "http_401")])

    assert payload["summary"]["total"] == 1
    assert payload["summary"]["healthy"] == 0
    assert payload["results"][0]["model_id"] == "mistral/mistral-small-latest"
