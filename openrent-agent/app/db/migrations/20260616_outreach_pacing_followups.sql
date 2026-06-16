ALTER TABLE accounts ADD COLUMN next_outreach_at DATETIME;
ALTER TABLE conversations ADD COLUMN last_outbound_at DATETIME;
ALTER TABLE conversations ADD COLUMN follow_up_count INTEGER DEFAULT 0;
