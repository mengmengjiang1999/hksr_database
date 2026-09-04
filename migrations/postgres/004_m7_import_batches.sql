ALTER TABLE hksr.import_batches
    DROP CONSTRAINT IF EXISTS import_batches_batch_id_check;

ALTER TABLE hksr.import_batches
    ADD CONSTRAINT import_batches_batch_id_check
    CHECK (batch_id ~ '^m(6b|7)-real-[a-z0-9][a-z0-9-]{2,59}$');
