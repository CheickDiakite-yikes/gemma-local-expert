ALTER TABLE conversation_messages ADD COLUMN evidence_packet_json TEXT;

CREATE INDEX IF NOT EXISTS idx_conversation_messages_turn_id_role
ON conversation_messages(turn_id, role);
