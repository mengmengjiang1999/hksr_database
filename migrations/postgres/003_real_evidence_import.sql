CREATE TABLE IF NOT EXISTS hksr.import_batches (
    batch_id text PRIMARY KEY CHECK (batch_id ~ '^m6b-real-[a-z0-9][a-z0-9-]{2,59}$'),
    source_fingerprint text NOT NULL,
    counts jsonb NOT NULL,
    imported_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW hksr.official_evidence AS
SELECT c.evidence_id, c.section_path, c.speaker, c.text,
       c.content_sha256, c.embedding
FROM hksr.chunks c
JOIN hksr.documents d ON d.id = c.document_id
JOIN hksr.sources s ON s.id = d.source_id
WHERE c.synthetic = false
  AND d.evidence_eligible = true
  AND s.status = 'parsed';

CREATE INDEX IF NOT EXISTS sources_status_idx ON hksr.sources(status);
CREATE INDEX IF NOT EXISTS documents_source_position_idx
    ON hksr.documents(source_id, position);
