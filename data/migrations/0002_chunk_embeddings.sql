ALTER TABLE knowledge_chunks ADD COLUMN chunk_index INTEGER NOT NULL DEFAULT 1;
ALTER TABLE knowledge_chunks ADD COLUMN token_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS knowledge_chunk_embeddings (
    chunk_id TEXT PRIMARY KEY REFERENCES knowledge_chunks(chunk_id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_knowledge_chunk_embeddings_provider_model
ON knowledge_chunk_embeddings(provider, model);
