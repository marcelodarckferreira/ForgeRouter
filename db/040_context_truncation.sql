-- Observability for the new lossy context-truncation safety valve
-- (app/normalize.py: truncate_messages, off by default via
-- ai_router.settings.context_truncation_enabled). 0/NULL means nothing was
-- dropped for that request — either truncation is disabled, or the request
-- was already under the configured token budget.
ALTER TABLE ai_router.route_events ADD COLUMN IF NOT EXISTS messages_dropped INTEGER;
