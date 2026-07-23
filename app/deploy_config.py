"""Writes a freshly rotated agent key into that agent's own runtime config file
and restarts its service, synchronously, as part of POST /admin/agents/{name}/rotate-key.

Deliberately NOT a YAML/dotenv parser-and-rewrite: it does a literal, exact-match
string replacement of the old key value with the new one. That preserves every
comment/formatting byte of a config file this app doesn't own, and — since agent
keys are long random tokens — an exact-match count of anything other than 1 is
itself the safety check (0 means the file doesn't actually hold the key we think
it does; >1 would mean an ambiguous replace, which never happens with real keys
but is checked anyway).

Every failure mode returns a result dict rather than raising past the caller —
the point of this module is that a failure is reported back in the same HTTP
response, never left as a silent, undetectable pending state (see the incident
this whole feature responds to: Scriba silently running on Athos's stale key).
"""

from __future__ import annotations

import subprocess


def apply_agent_deploy_config(
    old_key: str,
    new_key: str,
    config_path: str | None,
    config_format: str | None,
    restart_service: str | None,
) -> dict:
    if not config_path:
        return {"applied": False, "status": "no_config", "detail": "No deploy-config set for this agent — key rotated in the database only."}

    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            content = handle.read()
    except OSError as exc:
        return {"applied": False, "status": "read_failed", "detail": f"Could not read {config_path}: {exc}"}

    occurrences = content.count(old_key)
    if occurrences == 0:
        return {
            "applied": False,
            "status": "old_key_not_found",
            "detail": f"The agent's current key was not found in {config_path} — it may already be out of sync. Check the file manually.",
        }
    if occurrences > 1:
        return {
            "applied": False,
            "status": "ambiguous_match",
            "detail": f"The current key appears {occurrences} times in {config_path} — refusing to guess which one. Update it manually.",
        }

    new_content = content.replace(old_key, new_key)
    try:
        with open(config_path, "w", encoding="utf-8") as handle:
            handle.write(new_content)
    except OSError as exc:
        return {"applied": False, "status": "write_failed", "detail": f"Could not write {config_path}: {exc}"}

    if not restart_service:
        return {"applied": True, "status": "written", "detail": f"Key written to {config_path}. No restart_service configured for this agent — it will pick up the new key on its next invocation."}

    try:
        result = subprocess.run(
            ["systemctl", "restart", restart_service],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as exc:
        return {
            "applied": True,
            "status": "restart_failed",
            "detail": f"Key written to {config_path}, but restarting {restart_service} raised {type(exc).__name__}: {exc}. Restart it manually.",
        }
    if result.returncode != 0:
        return {
            "applied": True,
            "status": "restart_failed",
            "detail": f"Key written to {config_path}, but `systemctl restart {restart_service}` exited {result.returncode}: {result.stderr.strip() or result.stdout.strip()}. Restart it manually.",
        }
    return {"applied": True, "status": "applied", "detail": f"Key written to {config_path} and {restart_service} restarted."}
