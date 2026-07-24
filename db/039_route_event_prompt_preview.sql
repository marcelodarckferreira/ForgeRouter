-- Short (~100 char) preview of the last user message, for audit visibility on
-- the Messages page — never the full prompt. Deliberately not the full body:
-- ForgeRouter does not persist conversation content by design (see CLAUDE.md);
-- this is a bounded compromise for auditability, not a reversal of that rule.
ALTER TABLE ai_router.route_events ADD COLUMN IF NOT EXISTS prompt_preview TEXT;
