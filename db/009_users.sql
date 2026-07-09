-- Dashboard login. The default admin/admin user is seeded by the app on first login
-- (ensure_default_user) with must_change_password = true.
CREATE TABLE IF NOT EXISTS ai_router.users (
    user_id BIGSERIAL PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    must_change_password BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_router.sessions (
    token TEXT PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES ai_router.users(user_id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL
);

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_router.users, ai_router.sessions TO proxyrouter_user;
GRANT USAGE, SELECT ON SEQUENCE ai_router.users_user_id_seq TO proxyrouter_user;
