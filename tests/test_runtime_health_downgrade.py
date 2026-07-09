from app.registry import ProviderModel
from app.storage import runtime_failure_health_result


def test_runtime_failure_health_result_marks_model_unhealthy():
    model = ProviderModel("p1/model-a", "p1", "model-a", 1, ["text"], True, True, "http://p1/v1", "")

    result = runtime_failure_health_result(model, http_code=500, error_message="http_500")

    assert result.model_id == "p1/model-a"
    assert result.status == "unhealthy"
    assert result.http_code == 500
    assert result.error_message == "http_500"
