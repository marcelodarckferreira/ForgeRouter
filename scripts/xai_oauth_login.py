#!/usr/bin/env python
"""Interactive xAI Grok (SuperGrok / X Premium+) OAuth device-code login.

Unlike the other subscription adapters (Claude Code, Codex, Antigravity,
Z.ai) there is no existing CLI already logged in on this host that keeps
~/.xai/auth.json fresh — xAI has no first-party CLI for this. This script is
the one deliberate exception in this codebase to "ForgeRouter does not
automate login": it runs the OAuth 2.0 device-authorization grant against
auth.x.ai, prints a verification URL + code for you to approve in any
browser (does not need to be on this machine), polls until approved, and
writes the token file `app/providers/xai_grok.py` reads/refreshes from.

Run it once (and again if the refresh token is ever revoked):

    docker compose run --rm -e PYTHONPATH=/app forgerouter python scripts/xai_oauth_login.py

Known limitation (not something this script can work around): xAI has been
reported to return 403 on this OAuth surface for some SuperGrok subscribers
despite an active subscription, via an account-side allowlist. If that
happens after a successful login here, the fallback is a plain XAI_API_KEY
provider (console.x.ai) instead of OAuth.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.providers.xai_grok import (  # noqa: E402
    XAI_AUTH_FILE,
    XAI_CLIENT_ID,
    XAI_CLIENT_VERSION,
    XAI_DEVICE_CODE_URL,
    XAI_DEVICE_GRANT_TYPE,
    XAI_REFRESH_SKEW_SECONDS,
    XAI_SCOPE,
    XAI_TOKEN_URL,
    _write_auth_file,
    xai_grok_discover_models,
)

DEVICE_HEADERS = {
    "Content-Type": "application/x-www-form-urlencoded",
    "x-grok-client-version": XAI_CLIENT_VERSION,
    "x-grok-client-surface": "cli",
}


def request_device_code() -> dict:
    response = httpx.post(
        XAI_DEVICE_CODE_URL,
        data={"client_id": XAI_CLIENT_ID, "scope": XAI_SCOPE, "referrer": "forgerouter"},
        headers=DEVICE_HEADERS,
        timeout=15.0,
    )
    response.raise_for_status()
    return response.json()


def poll_for_token(device_code: str, interval: int, expires_in: int) -> dict:
    deadline = time.time() + max(expires_in, 60)
    while time.time() < deadline:
        time.sleep(interval)
        response = httpx.post(
            XAI_TOKEN_URL,
            data={"grant_type": XAI_DEVICE_GRANT_TYPE, "device_code": device_code, "client_id": XAI_CLIENT_ID},
            headers=DEVICE_HEADERS,
            timeout=15.0,
        )
        if response.status_code == 200:
            return response.json()
        try:
            error = response.json().get("error", "")
        except Exception:
            error = ""
        if error == "authorization_pending":
            continue
        if error == "slow_down":
            interval += 5
            continue
        if error == "access_denied":
            raise SystemExit("xAI login denied.")
        if error == "expired_token":
            raise SystemExit("Device code expired — rerun this script.")
        raise SystemExit(f"xAI device token exchange failed: {error or response.status_code}")
    raise SystemExit("Timed out waiting for approval — rerun this script.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Log in to xAI Grok (SuperGrok/X Premium+) via OAuth device code")
    parser.parse_args()

    device = request_device_code()
    display_url = device.get("verification_uri_complete") or device.get("verification_uri")
    print(f"Open this URL and approve the login: {display_url}")
    if not device.get("verification_uri_complete"):
        print(f"Enter code: {device.get('user_code')}")
    print("Waiting for approval...")

    token = poll_for_token(
        device["device_code"],
        interval=int(device.get("interval") or 5),
        expires_in=int(device.get("expires_in") or 600),
    )

    access_token = token.get("access_token")
    refresh_token = token.get("refresh_token")
    if not access_token or not refresh_token:
        raise SystemExit(f"xAI token response missing access_token/refresh_token: {token}")

    _write_auth_file({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": time.time() + float(token.get("expires_in") or 3600) - XAI_REFRESH_SKEW_SECONDS,
        "token_endpoint": XAI_TOKEN_URL,
    })
    print(json.dumps({
        "status": "ok",
        "auth_file": XAI_AUTH_FILE,
        "models": [m["id"] for m in xai_grok_discover_models()],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
