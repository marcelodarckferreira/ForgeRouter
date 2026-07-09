-- User accounts + access profiles (ForgeHub-style RBAC for the dashboard).
-- A Profile groups per-module permission flags; users get exactly one
-- profile (nullable). Admins bypass all checks. The four flags per module
-- mirror ForgeHub's profile_permissions: view / query / write / delete.
CREATE TABLE IF NOT EXISTS ai_router.profiles (
    profile_id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ai_router.profile_permissions (
    profile_id BIGINT NOT NULL REFERENCES ai_router.profiles(profile_id) ON DELETE CASCADE,
    module TEXT NOT NULL,
    can_view BOOLEAN NOT NULL DEFAULT TRUE,
    can_query BOOLEAN NOT NULL DEFAULT TRUE,
    can_write BOOLEAN NOT NULL DEFAULT FALSE,
    can_delete BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (profile_id, module)
);

ALTER TABLE ai_router.users ADD COLUMN IF NOT EXISTS full_name TEXT;
ALTER TABLE ai_router.users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE ai_router.users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE ai_router.users ADD COLUMN IF NOT EXISTS profile_id BIGINT REFERENCES ai_router.profiles(profile_id) ON DELETE SET NULL;

-- The primary (oldest) user is the seeded admin — keep it all-powerful so
-- nobody gets locked out by the new gating.
UPDATE ai_router.users SET is_admin = TRUE
WHERE user_id = (SELECT min(user_id) FROM ai_router.users);

GRANT SELECT, INSERT, UPDATE, DELETE ON ai_router.profiles, ai_router.profile_permissions TO proxyrouter_user;
GRANT USAGE, SELECT ON SEQUENCE ai_router.profiles_profile_id_seq TO proxyrouter_user;
