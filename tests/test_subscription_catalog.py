from app import storage


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def execute(self, query):
        self.query = query

    def fetchall(self):
        return [
            (
                "minimax",
                "MiniMax",
                "Pay-as-you-go",
                "https://api.minimax.chat/v1",
                "bearer",
                "minimax.io -> API Keys",
                "https://platform.minimax.io/",
                {},
            ),
            (
                "openai-codex",
                "OpenAI Codex",
                "ChatGPT Plus/Pro plan",
                "https://chatgpt.com/backend-api/codex",
                "oauth",
                "automatic — uses the Codex CLI login on the server",
                "",
                {},
            ),
        ]


class _Connection:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def cursor(self):
        return _Cursor()


def test_subscription_catalog_returns_each_plans_authentication_url(monkeypatch):
    monkeypatch.setattr(storage, "db_connect", lambda: _Connection())

    catalog = storage.list_subscription_catalog()

    assert catalog == [
        {
            "name": "minimax",
            "display_name": "MiniMax",
            "plan_hint": "Pay-as-you-go",
            "base_url": "https://api.minimax.chat/v1",
            "auth_method": "bearer",
            "token_hint": "minimax.io -> API Keys",
            "auth_url": "https://platform.minimax.io/",
            "extra_headers": {},
        },
        {
            "name": "openai-codex",
            "display_name": "OpenAI Codex",
            "plan_hint": "ChatGPT Plus/Pro plan",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "auth_method": "oauth",
            "token_hint": "automatic — uses the Codex CLI login on the server",
            "auth_url": "",
            "extra_headers": {},
        },
    ]
