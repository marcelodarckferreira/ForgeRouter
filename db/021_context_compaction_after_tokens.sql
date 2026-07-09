-- "Tokens saved" must isolate the effect of context compaction itself: compare
-- a tiktoken estimate of the messages array before normalization
-- (prompt_tokens_raw, added in 020) against the same estimate after
-- normalization (prompt_tokens_compacted). Both use the same tokenizer and the
-- same JSON representation, so the delta reflects only what normalize_messages
-- removed — and is ~0 when context compaction is disabled.
ALTER TABLE ai_router.route_events
    ADD COLUMN IF NOT EXISTS prompt_tokens_compacted INTEGER;
