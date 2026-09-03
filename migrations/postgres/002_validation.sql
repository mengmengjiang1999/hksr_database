CREATE SCHEMA IF NOT EXISTS hksr_validation;

CREATE TABLE IF NOT EXISTS hksr_validation.runs (
    run_id text PRIMARY KEY CHECK (run_id ~ '^m6b-[a-z0-9][a-z0-9-]{2,59}$'),
    chunk_count integer NOT NULL CHECK (chunk_count BETWEEN 1 AND 1000000),
    dimensions integer NOT NULL CHECK (dimensions = 1024),
    synthetic boolean NOT NULL DEFAULT true CHECK (synthetic = true),
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS hksr_validation.chunks (
    run_id text NOT NULL REFERENCES hksr_validation.runs(run_id) ON DELETE CASCADE,
    ordinal integer NOT NULL,
    evidence_id text NOT NULL,
    text text NOT NULL,
    search_vector tsvector GENERATED ALWAYS AS (to_tsvector('simple', text)) STORED,
    embedding vector(1024) NOT NULL,
    synthetic boolean NOT NULL DEFAULT true CHECK (synthetic = true),
    PRIMARY KEY (run_id, ordinal),
    UNIQUE (evidence_id)
);

CREATE INDEX IF NOT EXISTS validation_chunks_run_idx
    ON hksr_validation.chunks(run_id);
CREATE INDEX IF NOT EXISTS validation_chunks_search_idx
    ON hksr_validation.chunks USING gin(search_vector);

CREATE OR REPLACE VIEW hksr.official_evidence AS
SELECT evidence_id, section_path, speaker, text, content_sha256, embedding
FROM hksr.chunks
WHERE synthetic = false;
