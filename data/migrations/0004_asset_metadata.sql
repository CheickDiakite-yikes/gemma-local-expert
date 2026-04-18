ALTER TABLE assets ADD COLUMN display_name TEXT;
ALTER TABLE assets ADD COLUMN media_type TEXT;
ALTER TABLE assets ADD COLUMN kind TEXT NOT NULL DEFAULT 'document';
ALTER TABLE assets ADD COLUMN byte_size INTEGER;
ALTER TABLE assets ADD COLUMN local_path TEXT;
ALTER TABLE assets ADD COLUMN care_context TEXT NOT NULL DEFAULT 'general';
ALTER TABLE assets ADD COLUMN analysis_status TEXT NOT NULL DEFAULT 'metadata_only';
ALTER TABLE assets ADD COLUMN analysis_summary TEXT;

CREATE TABLE IF NOT EXISTS conversation_message_assets (
    message_id TEXT NOT NULL REFERENCES conversation_messages(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    PRIMARY KEY (message_id, asset_id)
);

CREATE INDEX IF NOT EXISTS idx_conversation_message_assets_message_id
ON conversation_message_assets(message_id);
