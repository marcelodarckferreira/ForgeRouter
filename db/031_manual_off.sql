-- Manual vs automatic off: a model unchecked by hand stays off permanently
-- (rescan/resync never re-enable it); a model unchecked by a health verdict
-- is revivable — the rescan keeps scanning it and turns it back on when it
-- recovers.
ALTER TABLE ai_router.models ADD COLUMN IF NOT EXISTS manual_off BOOLEAN NOT NULL DEFAULT false;
-- Freeze today's curation: everything currently off was a deliberate choice.
UPDATE ai_router.models SET manual_off = true WHERE NOT enabled;
