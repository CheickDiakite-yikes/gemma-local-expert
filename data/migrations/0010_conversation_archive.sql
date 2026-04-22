ALTER TABLE conversations ADD COLUMN archived_at TEXT;

CREATE INDEX IF NOT EXISTS idx_conversations_archived_at
ON conversations(archived_at);
