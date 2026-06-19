-- Reference migration for deployments that manage schema outside init_db().
-- The application also creates lead_sheet_exports and adds listing columns
-- automatically during init_db().

ALTER TABLE listings ADD COLUMN IF NOT EXISTS property_address VARCHAR;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS bedrooms INTEGER;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS bathrooms INTEGER;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS rent_pcm INTEGER;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS landlord_name VARCHAR;
ALTER TABLE listings ADD COLUMN IF NOT EXISTS metadata_captured_at TIMESTAMP;

CREATE TABLE IF NOT EXISTS lead_sheet_exports (
    id SERIAL PRIMARY KEY,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id),
    status VARCHAR NOT NULL DEFAULT 'PENDING',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TIMESTAMP,
    processing_started_at TIMESTAMP,
    last_error TEXT,
    destination_tab VARCHAR,
    destination_row INTEGER,
    payload_hash VARCHAR,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    exported_at TIMESTAMP,
    CONSTRAINT uq_lead_sheet_export_conversation UNIQUE (conversation_id)
);
