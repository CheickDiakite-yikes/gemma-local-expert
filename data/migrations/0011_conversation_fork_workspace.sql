ALTER TABLE conversations ADD COLUMN workspace_binding_json TEXT;
ALTER TABLE conversations ADD COLUMN parent_conversation_id TEXT;
ALTER TABLE conversations ADD COLUMN forked_from_turn_id TEXT;

CREATE INDEX IF NOT EXISTS idx_conversations_parent_conversation_id
ON conversations(parent_conversation_id);
