-- Postgres syntax (production driver is psycopg2). This is also registered
-- in app/db/init_db.py REQUIRED_COLUMNS and applied automatically on app
-- startup — this file is kept for the historical record / manual unblock.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS next_outreach_at TIMESTAMP;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS last_outbound_at TIMESTAMP;
ALTER TABLE conversations ADD COLUMN IF NOT EXISTS follow_up_count INTEGER DEFAULT 0;
