-- Postgres syntax. Also registered in app/db/init_db.py REQUIRED_COLUMNS and
-- applied automatically on app startup — this file is kept for the
-- historical record / manual unblock.
ALTER TABLE proxies ADD COLUMN IF NOT EXISTS proxy_type VARCHAR DEFAULT 'static';
