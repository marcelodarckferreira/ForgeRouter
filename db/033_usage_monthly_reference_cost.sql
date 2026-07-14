-- Mirrors route_events.reference_cost (db/032) into the monthly rollup so
-- yearly_usage_by_agent (the year-to-date view, which reads archived months
-- once raw route_events are pruned) doesn't lose reference-cost visibility
-- after archival.
ALTER TABLE ai_router.usage_monthly ADD COLUMN IF NOT EXISTS reference_cost NUMERIC(14, 6) NOT NULL DEFAULT 0;
