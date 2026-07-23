-- Optional per-agent deploy-config location: where the agent's own runtime
-- config actually lives, so an admin action (POST rotate-key) can write the
-- freshly rotated key there directly instead of leaving the agent silently
-- running on a stale key until someone notices and updates it by hand (see
-- the Scriba/Athos key-mixup incident, 2026-07-23).
--
-- config_format is 'yaml' (a dotted key path into a YAML file, e.g.
-- providers.forgerouter.api_key) or 'env' (a KEY=value line in a dotenv
-- file, e.g. FORGEROUTER_API_KEY). restart_service is the systemd unit to
-- restart after the write; NULL means nothing to restart (CLI-invoked
-- agents like Aramis/Porthos/Dartan pick up a new .env on their next
-- invocation, no running daemon to bounce).
--
-- All four columns are NULL by default: rotate-key keeps working exactly as
-- before (DB-only) for any agent that hasn't been given a deploy-config yet.
ALTER TABLE ai_router.agents
    ADD COLUMN IF NOT EXISTS config_path TEXT,
    ADD COLUMN IF NOT EXISTS config_format TEXT,
    ADD COLUMN IF NOT EXISTS config_key TEXT,
    ADD COLUMN IF NOT EXISTS restart_service TEXT;

ALTER TABLE ai_router.agents DROP CONSTRAINT IF EXISTS agents_config_format_check;
ALTER TABLE ai_router.agents ADD CONSTRAINT agents_config_format_check CHECK (config_format IS NULL OR config_format IN ('yaml', 'env'));
