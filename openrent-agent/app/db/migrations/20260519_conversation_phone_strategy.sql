ALTER TABLE accounts ADD COLUMN mobile_number VARCHAR;
ALTER TABLE accounts ADD COLUMN phone_fetching_type VARCHAR;
ALTER TABLE accounts ADD COLUMN message_strategy VARCHAR;
ALTER TABLE accounts ADD COLUMN escalation_behavior VARCHAR;
ALTER TABLE accounts ADD COLUMN conversation_goal VARCHAR;
ALTER TABLE accounts ADD COLUMN conversation_style VARCHAR;

ALTER TABLE conversations ADD COLUMN phone_found_at DATETIME;
ALTER TABLE conversations ADD COLUMN phone_number_shared_at DATETIME;
ALTER TABLE conversations ADD COLUMN landlord_asked_phone_at DATETIME;
ALTER TABLE conversations ADD COLUMN landlord_attitude VARCHAR DEFAULT 'responsive';
ALTER TABLE conversations ADD COLUMN conversation_style VARCHAR;
