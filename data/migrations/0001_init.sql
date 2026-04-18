CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_conversation_messages_conversation_id
ON conversation_messages(conversation_id);

CREATE TABLE IF NOT EXISTS knowledge_packs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    description TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    description TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL UNIQUE,
    knowledge_pack_id TEXT NOT NULL REFERENCES knowledge_packs(id) ON DELETE CASCADE,
    asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    label TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunks_pack_id
ON knowledge_chunks(knowledge_pack_id);

CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_chunks_fts
USING fts5(
    chunk_id UNINDEXED,
    knowledge_pack_id UNINDEXED,
    asset_id UNINDEXED,
    label,
    text
);

CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_approvals_conversation_id
ON approvals(conversation_id);

CREATE TABLE IF NOT EXISTS medical_sessions (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exports (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    export_type TEXT NOT NULL,
    destination_path TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    details_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_log_event_type
ON audit_log(event_type);
