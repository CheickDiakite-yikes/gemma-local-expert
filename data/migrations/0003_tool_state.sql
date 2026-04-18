ALTER TABLE approvals ADD COLUMN payload_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE approvals ADD COLUMN result_json TEXT;
ALTER TABLE approvals ADD COLUMN executed_at TEXT;

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    kind TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL
);
