-- Meta-router models ("auto"/"auto-beta") pick an unknown underlying model per
-- request instead of being a real, specific model — unpredictable behavior for
-- routing/health scoring purposes. Disabled by hand at Marcelo's request
-- (2026-07-23), same manual_off semantics as any dashboard uncheck: permanent,
-- survives rescan/resync, never re-enabled automatically.
UPDATE ai_router.models
SET enabled = false, manual_off = true
WHERE public_id IN (
    'openrouter/openrouter/auto',
    'openrouter/openrouter/auto-beta',
    'Kilo/kilo-auto/free'
);
