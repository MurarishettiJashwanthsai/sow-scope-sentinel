CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS contract_documents (
    id BIGSERIAL PRIMARY KEY,
    parent_contract_id BIGINT REFERENCES contract_documents(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    document_type TEXT NOT NULL CHECK (document_type IN ('SOW', 'AMENDMENT')),
    effective_date DATE,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    supersedes_clause_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    source_filename TEXT,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS contract_clauses (
    id BIGSERIAL PRIMARY KEY,
    contract_id BIGINT NOT NULL REFERENCES contract_documents(id) ON DELETE CASCADE,
    clause_ref TEXT NOT NULL,
    category TEXT NOT NULL,
    text TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    embedding vector(1536),
    UNIQUE(contract_id, clause_ref, ordinal)
);

CREATE INDEX IF NOT EXISTS contract_clause_embedding_hnsw
ON contract_clauses USING hnsw (embedding vector_cosine_ops);

-- Example retrieval query. Bind :embedding and :contract_ids in the application.
-- SELECT id, clause_ref, text, 1 - (embedding <=> :embedding) AS similarity
-- FROM contract_clauses
-- WHERE contract_id = ANY(:contract_ids)
-- ORDER BY embedding <=> :embedding
-- LIMIT 8;

