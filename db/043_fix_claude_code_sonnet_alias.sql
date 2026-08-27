-- Claude Code accepts the rolling Sonnet 4.6 alias; the dated fallback ID
-- previously cataloged by ForgeRouter returns model_not_found.
UPDATE ai_router.models AS model
SET public_id = 'claude-code/claude-sonnet-4-6',
    provider_model = 'claude-sonnet-4-6'
FROM ai_router.providers AS provider
WHERE model.provider_id = provider.provider_id
  AND provider.name = 'claude-code'
  AND model.public_id = 'claude-code/claude-sonnet-4-6-20251114'
  AND NOT EXISTS (
      SELECT 1
      FROM ai_router.models AS existing
      WHERE existing.public_id = 'claude-code/claude-sonnet-4-6'
  );
