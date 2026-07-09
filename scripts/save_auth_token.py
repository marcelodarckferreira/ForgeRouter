#!/usr/bin/env python
"""Save a manually-copied session token to a provider's auth file.

No browser automation: log in yourself in your normal, everyday browser
(chat.z.ai's and chat.deepseek.com's anti-bot edge blocks automated/headless
browsers, so this has to be a real session you logged into by hand), open
DevTools, copy the token, and paste it here. This only writes the file
ForgeRouter's plan handlers (app/providers/zai.py, app/providers/deepseek_web.py)
already read — it does not touch the network.

Run on the HOST, not inside the ForgeRouter Docker container: docker-compose
mounts ~/.zai and ~/.deepseek read-only into the container, so a write from
inside it would fail.

    python3 scripts/save_auth_token.py --provider zai
    python3 scripts/save_auth_token.py --provider deepseek
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path

PROVIDERS = {
    "zai": {
        "env_var": "ZAI_AUTH_FILE",
        "default_path": "~/.zai/auth.json",
        "key": "access_token",
        "hint": "chat.z.ai -> DevTools -> Application -> Local Storage -> the 'token' entry under https://chat.z.ai",
    },
    "deepseek": {
        "env_var": "DEEPSEEK_WEB_AUTH_FILE",
        "default_path": "~/.deepseek/auth.json",
        "key": "token",
        "hint": "chat.deepseek.com -> DevTools -> Application -> Local Storage -> the user token entry under https://chat.deepseek.com",
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a manually-copied subscription token")
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    args = parser.parse_args()

    spec = PROVIDERS[args.provider]
    auth_file = os.environ.get(spec["env_var"], spec["default_path"])

    print(f"Copy the token from: {spec['hint']}")
    token = getpass.getpass("Token (input hidden): ").strip()
    if not token:
        print("No token entered, nothing saved.")
        return 2

    path = Path(auth_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({spec["key"]: token}, indent=2))
    path.chmod(0o600)
    print(f"Saved to {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
