-- E-mail on user accounts (optional, unique when present — same as ForgeHub).
ALTER TABLE ai_router.users ADD COLUMN IF NOT EXISTS email TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS users_email_unique
    ON ai_router.users (lower(email)) WHERE email IS NOT NULL;
