CREATE TABLE IF NOT EXISTS conversation_turns (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    mode TEXT NOT NULL,
    user_text TEXT NOT NULL,
    workspace_root TEXT NOT NULL,
    cwd TEXT NOT NULL,
    policy_json TEXT NOT NULL,
    route_kind TEXT,
    user_message_id TEXT,
    assistant_message_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_turns_conversation_created
ON conversation_turns(conversation_id, created_at DESC);

CREATE TABLE IF NOT EXISTS conversation_items (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL,
    item_kind TEXT NOT NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_items_conversation_created
ON conversation_items(conversation_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_conversation_items_turn_created
ON conversation_items(turn_id, created_at DESC);
