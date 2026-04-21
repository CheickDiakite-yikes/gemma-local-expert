CREATE TABLE IF NOT EXISTS conversation_memories (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    topic TEXT NOT NULL,
    summary TEXT NOT NULL,
    keywords_json TEXT NOT NULL DEFAULT '[]',
    source_domain TEXT,
    asset_ids_json TEXT NOT NULL DEFAULT '[]',
    tool_name TEXT,
    referent_title TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_memories_conversation_created
ON conversation_memories(conversation_id, created_at DESC);
