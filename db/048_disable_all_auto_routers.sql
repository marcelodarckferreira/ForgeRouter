-- Disable all meta-router / auto models across all providers permanently.
UPDATE ai_router.models
SET enabled = false, manual_off = true
WHERE provider_model ~* '^(openrouter/auto|kilo-auto|auto|openrouter/bodybuilder|openrouter/fusion|openrouter/free|openrouter/pareto-code)'
   OR public_id ~* '/auto'
   OR public_id IN (
       'openrouter/openrouter/auto',
       'openrouter/openrouter/auto-beta',
       'Kilo/openrouter/auto',
       'Kilo/openrouter/auto-beta',
       'Kilo/kilo-auto/free',
       'Kilo/kilo-auto/balanced',
       'Kilo/kilo-auto/efficient',
       'Kilo/kilo-auto/frontier',
       'Kilo/openrouter/bodybuilder',
       'openrouter/openrouter/bodybuilder',
       'Kilo/openrouter/fusion',
       'openrouter/openrouter/fusion',
       'Kilo/openrouter/pareto-code',
       'openrouter/openrouter/pareto-code',
       'Kilo/openrouter/free',
       'openrouter/openrouter/free'
   );
