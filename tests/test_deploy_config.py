import subprocess

from app.deploy_config import apply_agent_deploy_config


def test_no_config_path():
    result = apply_agent_deploy_config("old-key", "new-key", None, "env", "some.service")
    assert result == {"applied": False, "status": "no_config", "detail": "No deploy-config set for this agent — key rotated in the database only."}


def test_read_failed(tmp_path):
    missing = tmp_path / "does-not-exist.env"
    result = apply_agent_deploy_config("old-key", "new-key", str(missing), "env", None)
    assert result["applied"] is False
    assert result["status"] == "read_failed"
    assert str(missing) in result["detail"]


def test_old_key_not_found(tmp_path):
    config = tmp_path / "agent.env"
    config.write_text("AGENT_API_KEY=some-other-key\n", encoding="utf-8")
    result = apply_agent_deploy_config("old-key", "new-key", str(config), "env", None)
    assert result == {
        "applied": False,
        "status": "old_key_not_found",
        "detail": f"The agent's current key was not found in {config} — it may already be out of sync. Check the file manually.",
    }
    assert config.read_text(encoding="utf-8") == "AGENT_API_KEY=some-other-key\n"


def test_ambiguous_match_refuses_to_guess(tmp_path):
    config = tmp_path / "agent.env"
    config.write_text("AGENT_API_KEY=old-key\nBACKUP_KEY=old-key\n", encoding="utf-8")
    result = apply_agent_deploy_config("old-key", "new-key", str(config), "env", None)
    assert result["applied"] is False
    assert result["status"] == "ambiguous_match"
    assert "2 times" in result["detail"]
    # Refuses to guess: the file must be left completely untouched.
    assert config.read_text(encoding="utf-8") == "AGENT_API_KEY=old-key\nBACKUP_KEY=old-key\n"


def test_write_succeeds_without_restart_service(tmp_path):
    config = tmp_path / "agent.env"
    config.write_text("AGENT_API_KEY=old-key\nOTHER=unrelated\n", encoding="utf-8")
    result = apply_agent_deploy_config("old-key", "new-key", str(config), "env", None)
    assert result["applied"] is True
    assert result["status"] == "written"
    assert config.read_text(encoding="utf-8") == "AGENT_API_KEY=new-key\nOTHER=unrelated\n"


def test_write_and_restart_succeed(tmp_path, monkeypatch):
    config = tmp_path / "agent.env"
    config.write_text("AGENT_API_KEY=old-key\n", encoding="utf-8")

    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

    monkeypatch.setattr("app.deploy_config.subprocess.run", fake_run)
    result = apply_agent_deploy_config("old-key", "new-key", str(config), "env", "myagent.service")

    assert result == {"applied": True, "status": "applied", "detail": f"Key written to {config} and myagent.service restarted."}
    assert config.read_text(encoding="utf-8") == "AGENT_API_KEY=new-key\n"
    assert calls == [["systemctl", "restart", "myagent.service"]]


def test_write_succeeds_restart_returns_nonzero(tmp_path, monkeypatch):
    config = tmp_path / "agent.env"
    config.write_text("AGENT_API_KEY=old-key\n", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="Unit not found")

    monkeypatch.setattr("app.deploy_config.subprocess.run", fake_run)
    result = apply_agent_deploy_config("old-key", "new-key", str(config), "env", "myagent.service")

    # The key write itself already succeeded and must not be reported as failed —
    # only the restart step is in trouble.
    assert result["applied"] is True
    assert result["status"] == "restart_failed"
    assert "Unit not found" in result["detail"]
    assert config.read_text(encoding="utf-8") == "AGENT_API_KEY=new-key\n"


def test_write_succeeds_restart_raises(tmp_path, monkeypatch):
    config = tmp_path / "agent.env"
    config.write_text("AGENT_API_KEY=old-key\n", encoding="utf-8")

    def fake_run(cmd, **kwargs):
        raise FileNotFoundError("systemctl not found")

    monkeypatch.setattr("app.deploy_config.subprocess.run", fake_run)
    result = apply_agent_deploy_config("old-key", "new-key", str(config), "env", "myagent.service")

    assert result["applied"] is True
    assert result["status"] == "restart_failed"
    assert "FileNotFoundError" in result["detail"]
    assert config.read_text(encoding="utf-8") == "AGENT_API_KEY=new-key\n"


def test_write_failed(tmp_path, monkeypatch):
    config = tmp_path / "agent.env"
    config.write_text("AGENT_API_KEY=old-key\n", encoding="utf-8")

    real_open = open

    def fake_open(path, mode="r", *args, **kwargs):
        if "w" in mode:
            raise OSError("disk full")
        return real_open(path, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)
    result = apply_agent_deploy_config("old-key", "new-key", str(config), "env", None)

    assert result["applied"] is False
    assert result["status"] == "write_failed"
    assert "disk full" in result["detail"]
