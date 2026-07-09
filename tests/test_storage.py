from app.storage import health_to_row
from app.validation.health import HealthResult


def test_health_to_row_maps_result_fields():
    row = health_to_row(HealthResult("local/qwen2.5:1.5b", "unhealthy", None, 20, "ConnectError"))

    assert row["model_id"] == "local/qwen2.5:1.5b"
    assert row["status"] == "unhealthy"
    assert row["http_code"] is None
    assert row["latency_ms"] == 20
    assert row["error_message"] == "ConnectError"
