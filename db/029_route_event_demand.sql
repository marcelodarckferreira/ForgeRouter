-- Demand class the router resolved for the request (forgerouter/auto classification
-- or an explicit forgerouter/<demand>); NULL when a concrete model id was requested.
-- Lets the dashboard show the real per-demand distribution and audit misclassifications.
ALTER TABLE ai_router.route_events ADD COLUMN IF NOT EXISTS demand TEXT;
