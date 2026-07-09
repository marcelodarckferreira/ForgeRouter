from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_login_rejects_invalid_credentials(monkeypatch):
    monkeypatch.setattr("app.main.ensure_default_user", lambda: None)
    monkeypatch.setattr("app.main.authenticate_user", lambda username, password: None)

    response = client.post("/auth/login", json={"username": "admin", "password": "wrong"})

    assert response.status_code == 401


def test_login_returns_session_and_first_access_flag(monkeypatch):
    monkeypatch.setattr("app.main.ensure_default_user", lambda: None)
    monkeypatch.setattr(
        "app.main.authenticate_user",
        lambda username, password: {"user_id": 1, "username": "admin", "must_change_password": True},
    )
    monkeypatch.setattr("app.main.create_session", lambda user_id: "tok123")

    response = client.post("/auth/login", json={"username": "admin", "password": "admin"})

    assert response.status_code == 200
    body = response.json()
    assert body["token"] == "tok123"
    assert body["username"] == "admin"
    assert body["must_change_password"] is True
    assert body["is_admin"] is False
    # Non-admin without a profile: the RBAC map exists but grants nothing.
    from app.storage import DASHBOARD_MODULES

    assert set(body["permissions"]) == set(DASHBOARD_MODULES)
    assert not any(flag for perms in body["permissions"].values() for flag in perms.values())


def test_login_reports_store_unavailable(monkeypatch):
    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr("app.main.ensure_default_user", boom)

    response = client.post("/auth/login", json={"username": "admin", "password": "admin"})

    assert response.status_code == 503


def test_me_requires_valid_session(monkeypatch):
    monkeypatch.setattr("app.main.session_user", lambda token: None)

    response = client.get("/auth/me", headers={"Authorization": "Bearer nope"})

    assert response.status_code == 401


def test_change_password_rejects_weak_password(monkeypatch):
    monkeypatch.setattr(
        "app.main.session_user",
        lambda token: {"user_id": 1, "username": "admin", "must_change_password": True},
    )

    response = client.post(
        "/auth/change-password",
        headers={"Authorization": "Bearer tok"},
        json={"current_password": "admin", "new_password": "admin"},
    )

    assert response.status_code == 400


def test_change_password_updates_credentials(monkeypatch):
    monkeypatch.setattr(
        "app.main.session_user",
        lambda token: {"user_id": 1, "username": "admin", "must_change_password": True},
    )
    saved = {}

    def fake_change(user_id, current_password, new_username, new_password):
        saved.update(user_id=user_id, current=current_password, username=new_username, password=new_password)
        return {"user_id": user_id, "username": new_username or "admin", "must_change_password": False}

    monkeypatch.setattr("app.main.change_credentials", fake_change)

    response = client.post(
        "/auth/change-password",
        headers={"Authorization": "Bearer tok"},
        json={"current_password": "admin", "new_password": "s3cret", "new_username": "marcelo"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == "marcelo"
    assert response.json()["must_change_password"] is False
    assert saved["password"] == "s3cret"


def test_change_password_rejects_wrong_current_password(monkeypatch):
    monkeypatch.setattr(
        "app.main.session_user",
        lambda token: {"user_id": 1, "username": "admin", "must_change_password": True},
    )
    monkeypatch.setattr("app.main.change_credentials", lambda *args: None)

    response = client.post(
        "/auth/change-password",
        headers={"Authorization": "Bearer tok"},
        json={"current_password": "wrong", "new_password": "s3cret"},
    )

    assert response.status_code == 401


def test_session_token_authorizes_admin_actions(monkeypatch):
    monkeypatch.setattr("app.main.has_any_agent", lambda: True)
    monkeypatch.setattr("app.main.find_agent_by_key", lambda key: "tester" if key == "sekret" else None)
    monkeypatch.setattr(
        "app.main.session_user",
        lambda token: {"user_id": 1, "username": "admin", "must_change_password": False} if token == "sess" else None,
    )
    monkeypatch.setattr("app.main.create_agent", lambda name, api_key, description="": None)

    denied = client.post("/admin/agents", json={"name": "athos"})
    allowed = client.post("/admin/agents", headers={"Authorization": "Bearer sess"}, json={"name": "athos"})

    assert denied.status_code == 401
    assert allowed.status_code == 200


def test_password_hash_roundtrip():
    from app.storage import hash_password, verify_password

    stored = hash_password("admin")
    assert verify_password(stored, "admin")
    assert not verify_password(stored, "other")
    assert not verify_password("garbage", "admin")
