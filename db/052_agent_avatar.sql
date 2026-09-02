-- Optional agent profile image. The dashboard crops/downscales uploads to a
-- compact 256px data URI before persistence, matching user profile avatars.
ALTER TABLE ai_router.agents ADD COLUMN IF NOT EXISTS avatar_data_url TEXT;
