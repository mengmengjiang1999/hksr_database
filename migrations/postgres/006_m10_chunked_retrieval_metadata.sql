CREATE TABLE IF NOT EXISTS hksr.retrieval_metadata_chunks (
    metadata_key text NOT NULL
        REFERENCES hksr.retrieval_metadata(key) ON DELETE CASCADE,
    ordinal integer NOT NULL CHECK (ordinal >= 0),
    payload bytea NOT NULL,
    PRIMARY KEY (metadata_key, ordinal)
);
