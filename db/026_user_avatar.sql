-- Self-uploaded profile photo, stored as a "data:image/...;base64,..." URI
-- directly in the row — same approach as ForgeHub: no static-file mount
-- exists for user content, and avatars are downscaled client-side (256px)
-- before upload, so a TEXT column is simpler than standing up file storage.
ALTER TABLE ai_router.users ADD COLUMN IF NOT EXISTS avatar_data_url TEXT;
