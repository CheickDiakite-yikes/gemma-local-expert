ALTER TABLE conversation_messages ADD COLUMN turn_id TEXT;

CREATE INDEX IF NOT EXISTS idx_conversation_messages_turn_id
ON conversation_messages(turn_id);
