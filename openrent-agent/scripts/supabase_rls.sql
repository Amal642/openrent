-- Supabase Row Level Security (RLS) setup
-- Run this in the Supabase SQL Editor (Dashboard → SQL Editor → New Query)
--
-- What this does:
--   1. Enables RLS on every sensitive table so the PostgREST API blocks
--      all anonymous reads/writes by default.
--   2. Creates a single ALLOW policy for the service_role (the role your
--      backend uses via DATABASE_URL). This keeps the backend working
--      while the public REST API returns 0 rows to everyone else.
--
-- Your backend connects directly via psycopg2/asyncpg as the postgres
-- superuser or service_role — RLS does NOT apply to that role by default,
-- so no backend code changes are needed.

-- -----------------------------------------------------------------------
-- 1. Enable RLS
-- -----------------------------------------------------------------------

ALTER TABLE accounts          ENABLE ROW LEVEL SECURITY;
ALTER TABLE proxies           ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations     ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages          ENABLE ROW LEVEL SECURITY;
ALTER TABLE listings          ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_profiles   ENABLE ROW LEVEL SECURITY;
ALTER TABLE locations         ENABLE ROW LEVEL SECURITY;
ALTER TABLE landlords         ENABLE ROW LEVEL SECURITY;
ALTER TABLE lead_sheet_exports ENABLE ROW LEVEL SECURITY;

-- -----------------------------------------------------------------------
-- 2. Grant service_role full access (your backend connection role)
-- -----------------------------------------------------------------------

-- accounts
CREATE POLICY "service_role_all_accounts"
  ON accounts
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- proxies
CREATE POLICY "service_role_all_proxies"
  ON proxies
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- conversations
CREATE POLICY "service_role_all_conversations"
  ON conversations
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- messages
CREATE POLICY "service_role_all_messages"
  ON messages
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- listings
CREATE POLICY "service_role_all_listings"
  ON listings
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- search_profiles
CREATE POLICY "service_role_all_search_profiles"
  ON search_profiles
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- locations
CREATE POLICY "service_role_all_locations"
  ON locations
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- landlords
CREATE POLICY "service_role_all_landlords"
  ON landlords
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- lead_sheet_exports
CREATE POLICY "service_role_all_lead_sheet_exports"
  ON lead_sheet_exports
  FOR ALL
  TO service_role
  USING (true)
  WITH CHECK (true);

-- -----------------------------------------------------------------------
-- 3. Verify: these should now return 0 rows via the public API
--    (test in a new browser tab → Supabase Table Editor without signing in)
-- -----------------------------------------------------------------------
-- SELECT * FROM accounts;       -- should be blocked
-- SELECT * FROM proxies;        -- should be blocked
-- SELECT * FROM conversations;  -- should be blocked
