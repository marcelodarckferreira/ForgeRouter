-- Per-row runtime cooldown: a 429 honors the provider's Retry-After header
-- instead of the fixed 10-minute window. NULL = default 600 seconds.
ALTER TABLE ai_router.provider_health ADD COLUMN IF NOT EXISTS cooldown_seconds INTEGER;
