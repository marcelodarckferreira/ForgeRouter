#!/usr/bin/env python
"""Check and operationally recover Z.ai web subscription access.

This script intentionally does not automate browser login, passwords, captchas
or extraction of private chat.z.ai cookies. It verifies the same token resolver
used by ForgeRouter: local auth file first, then anonymous free token.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.providers.zai import ZAI_AUTH_FILE, _jwt_user_id, zai_discover_models, zai_token


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ForgeRouter Z.ai OAuth/session access")
    parser.parse_args()

    token = zai_token()
    if not token:
        print(json.dumps({
            "status": "missing_token",
            "auth_file": ZAI_AUTH_FILE,
            "recovery": [
                "Sign in through an approved Z.ai login/CLI flow.",
                "Write the access token to the auth file as {\"access_token\":\"...\"}.",
                "Mount/read that file in the ForgeRouter runtime or set ZAI_AUTH_FILE.",
            ],
        }, indent=2))
        return 2

    print(json.dumps({
        "status": "ok",
        "auth_file": ZAI_AUTH_FILE,
        "token_shape": "jwt" if _jwt_user_id(token) else "opaque",
        "models": [item["id"] for item in zai_discover_models()],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
