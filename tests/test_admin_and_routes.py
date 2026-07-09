from fastapi.testclient import TestClient

from app.main import app
from app.storage import route_event_to_row

client = TestClient(app)


def test_admin_provider_health_endpoint_returns_list(monkeypatch):
    response = client.get("/admin/providers/health")

    assert response.status_code == 200
    payload = response.json()
    assert "providers" in payload
    assert isinstance(payload["providers"], list)


def test_route_event_to_row_maps_fields():
    row = route_event_to_row(
        request_id="00000000-0000-0000-0000-000000000001",
        selected_model_id="local/qwen2.5:1.5b",
        required_capability="text",
        status="success",
        error_type=None,
    )

    assert row["request_id"] == "00000000-0000-0000-0000-000000000001"
    assert row["selected_model_id"] == "local/qwen2.5:1.5b"
    assert row["required_capability"] == "text"
    assert row["status"] == "success"
    assert row["error_type"] is None
