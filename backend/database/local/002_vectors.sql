-- Local-only knowledge base, replacing S3 Vectors.
-- 1536 dimensions matches OpenAI text-embedding-3-small.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    text TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
