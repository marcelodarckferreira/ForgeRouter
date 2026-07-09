-- Hermes task map: TTS audio tags (Gemini TTS tag insertion) routes through the
-- new forgerouter/audio group — only audio-capable models (catalog) serve it.
-- Inserted right after Title Gen to mirror the Hermes model-settings order.
UPDATE ai_router.task_map SET position = position + 1
WHERE position >= 9
  AND NOT EXISTS (SELECT 1 FROM ai_router.task_map WHERE task = 'TTS Audio Tags');

INSERT INTO ai_router.task_map (task, hint, model, position) VALUES
    ('TTS Audio Tags', 'Gemini TTS tag insertion', 'forgerouter/audio', 9)
ON CONFLICT (task) DO NOTHING;
