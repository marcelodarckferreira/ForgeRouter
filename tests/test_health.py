from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # version/git_sha identify exactly what code is running (see CLAUDE.md: a
    # stale forgerouter:latest image went undetected for over a week without this).
    assert body["version"]
    assert body["git_sha"]
