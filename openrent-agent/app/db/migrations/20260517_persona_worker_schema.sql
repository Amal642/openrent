ALTER TABLE accounts ADD COLUMN persona_name VARCHAR;
ALTER TABLE accounts ADD COLUMN persona_partner_name VARCHAR;
ALTER TABLE accounts ADD COLUMN persona_job VARCHAR;
ALTER TABLE accounts ADD COLUMN persona_partner_job VARCHAR;
ALTER TABLE accounts ADD COLUMN home_city VARCHAR;
ALTER TABLE accounts ADD COLUMN worker_status VARCHAR DEFAULT 'idle';
ALTER TABLE accounts ADD COLUMN worker_last_heartbeat DATETIME;
ALTER TABLE accounts ADD COLUMN worker_last_error TEXT;
ALTER TABLE accounts ADD COLUMN current_worker_phase VARCHAR DEFAULT 'idle';
ALTER TABLE accounts ADD COLUMN last_login_at DATETIME;

ALTER TABLE listings ADD COLUMN processing_owner VARCHAR;
ALTER TABLE listings ADD COLUMN processing_started_at DATETIME;

ALTER TABLE conversations ADD COLUMN processing_owner VARCHAR;
ALTER TABLE conversations ADD COLUMN processing_started_at DATETIME;
ALTER TABLE conversations ADD COLUMN conversation_stage VARCHAR DEFAULT 'NEW_LEAD';
ALTER TABLE conversations ADD COLUMN viewing_datetime DATETIME;
ALTER TABLE conversations ADD COLUMN last_stage_change DATETIME;
ALTER TABLE conversations ADD COLUMN phone_requested_at DATETIME;
ALTER TABLE conversations ADD COLUMN viewing_confirmed BOOLEAN DEFAULT 0;
ALTER TABLE conversations ADD COLUMN viewing_cancelled BOOLEAN DEFAULT 0;
ALTER TABLE conversations ADD COLUMN cancel_required BOOLEAN DEFAULT 1;
ALTER TABLE conversations ADD COLUMN cancellation_sent_at DATETIME;
