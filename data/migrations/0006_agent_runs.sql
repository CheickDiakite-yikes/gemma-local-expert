CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    turn_id TEXT NOT NULL,
    goal TEXT NOT NULL,
    scope_root TEXT NOT NULL,
    status TEXT NOT NULL,
    plan_steps_json TEXT NOT NULL DEFAULT '[]',
    executed_steps_json TEXT NOT NULL DEFAULT '[]',
    result_summary TEXT,
    artifact_ids_json TEXT NOT NULL DEFAULT '[]',
    approval_id TEXT REFERENCES approvals(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_conversation_id
ON agent_runs(conversation_id);

CREATE INDEX IF NOT EXISTS idx_agent_runs_turn_id
ON agent_runs(turn_id);

ALTER TABLE approvals ADD COLUMN run_id TEXT;

CREATE INDEX IF NOT EXISTS idx_approvals_run_id
ON approvals(run_id);
