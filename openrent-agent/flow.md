# OpenRent Automation Production Flow

## System Flow

1. Operator opens the Vercel/Vite dashboard.
2. Dashboard polls FastAPI through `VITE_API_BASE_URL`:
   - `GET /api/accounts`
   - `GET /api/workers`
   - `GET /api/workers/status`
   - `GET /api/proxy-health`
   - `GET /api/leads`
   - `GET /api/metrics`
   - `GET /api/logs`
3. Operator starts an account worker from Accounts or Workers.
4. Frontend calls `POST /api/accounts/{account_id}/start`.
5. FastAPI validates the account, marks it `queued`, enqueues an RQ job on Redis, and persists `worker_job_id`.
6. RQ worker runs `run_account_worker_sync(account_id)`.
7. Worker loads the account from Supabase/Postgres and enters `run_account_worker`.
8. Worker starts a heartbeat loop that updates `worker_last_heartbeat` every 45 seconds.
9. If a proxy is configured, worker validates it before Playwright launch:
   - HTTPS request to `https://api.ipify.org`
   - HTTPS request to `https://www.openrent.co.uk`
   - Persists `proxy_status`, `proxy_ip`, `proxy_latency`, `proxy_last_checked`, `proxy_last_error`, and `proxy_failures`.
10. If proxy is unhealthy, worker exits before Playwright and leaves account in `proxy_error`.
11. If proxy is healthy, worker launches Playwright.
12. Browser context loads persistent Playwright `storage_state`.
13. Default session path is `sessions/account_{id}.json` unless account has a custom `session_file`.
14. Login flow validates authenticated state.
15. If the saved session is valid, login is skipped and `session_status=active`.
16. If the session expired, worker logs in, saves fresh `storage_state`, and updates session health.
17. If login fails or captcha is suspected, worker records `login_error` or `captcha_suspected`.
18. Worker determines account phase:
   - Sunday: replies only.
   - Alternating weekdays: some accounts send initial outreach and replies, others replies only.
19. Initial outreach phase claims uncontacted listings with a DB owner lock.
20. Before sending any new enquiry, code checks:
   - account stop signal
   - UK outreach window, `Europe/London`, 08:00-21:00, no Sunday initial outreach
   - per-account daily initial message limit
   - existing OpenRent thread
   - landlord agent detection
   - contactable message route
21. Initial message is generated through existing persona-aware AI logic.
22. Message is sent through OpenRent.
23. Thread id is extracted from the final URL or existing message page.
24. Backend persists:
   - listing contacted state
   - message URL
   - conversation
   - conversation status `INITIAL_MESSAGE_SENT`
   - outbound message copy
   - account message count
25. Reply phase reads OpenRent inbox, claims conversations by `processing_owner`, generates AI replies, persists messages/status, and releases the claim.
26. Viewing reminder phase processes reminder/cancellation workflows.
27. Worker marks completion, stores `worker_last_completed_at`, clears retry metadata, closes Playwright resources, stops heartbeat, and returns to idle.
28. Frontend polling reflects updated worker, proxy, session, lead, and metric state.

## Backend Routes Added Or Changed

- `GET /api/proxy-health`
  - Returns per-account proxy status, IP, latency, last check, last error, and failure count.
- `POST /api/accounts/{account_id}/check-proxy`
  - Runs full proxy validation through `api.ipify.org` and OpenRent, then persists the result.
- `POST /api/accounts/{account_id}/test-proxy`
  - Kept for compatibility, now delegates to the full proxy health checker.
- `POST /api/accounts/{account_id}/start`
  - Persists RQ job id and queued status.
- `POST /api/accounts/{account_id}/invalidate-session`
  - Deletes the resolved persistent session state path.
- `GET /api/workers`
  - Now includes job id, started time, last completion time, retry count, retry timestamp, and stale heartbeat flag.

## DB Fields Added

`accounts`:

- `proxy_status`
- `proxy_ip`
- `proxy_latency`
- `proxy_last_checked`
- `proxy_last_error`
- `proxy_failures`
- `session_status`
- `session_last_checked`
- `session_last_error`
- `session_auth_failures`
- `session_captcha_triggers`
- `worker_job_id`
- `worker_started_at`
- `worker_error`
- `worker_last_completed_at`
- `retry_count`
- `retry_limit`
- `retry_reason`
- `retry_next_at`
- `last_exception`
- `permanently_failed`
- `messages_sent_reset_at`

The project auto-applies missing columns from `app/db/init_db.py`. SQL reference is in:

`app/db/migrations/20260602_proxy_session_worker_status.sql`

## Frontend Flow

1. `src/routes/accounts.tsx`
   - Shows session status, auth failure count, captcha count, worker phase, retry metadata, proxy status, proxy IP, proxy latency, proxy error, job id, heartbeat, and last completion.
   - Manual proxy check calls `POST /api/accounts/{id}/check-proxy`.
2. `src/routes/workers.tsx`
   - Shows queued/running/retrying/proxy_error/login_error states.
   - Shows stale heartbeat warnings.
   - Shows job id, retry count, retry timestamp, started time, and completion time.
3. `src/api/openrent.ts`
   - Maps backend fields to strict frontend types.
4. `src/lib/types.ts`
   - Adds production statuses and health metadata.

## Production Behavior Implemented

- Proxy validation before Playwright launch.
- Proxy health persistence and UI visibility.
- Persistent Playwright storage state.
- Legacy cookie session compatibility.
- Session active/expired/login failed/captcha suspected tracking.
- Worker queued/running/error/proxy_error/login_error status tracking.
- RQ job id persistence.
- Heartbeat loop every 45 seconds.
- Stale worker detection in API/UI.
- RQ retry policy: 1 minute, 5 minutes, 15 minutes.
- UK-time initial outreach guard.
- UK-date daily initial enquiry counter reset.
- Initial outreach persistence path verified in code: contacted listing, thread id, conversation, status, outbound message.
- Existing anti-overlap conversation protection retained through `claim_conversation`.
- Existing listing dedup retained through global `listing_id` uniqueness.

## Still Requires Production Verification

- Supabase live write/read verification with real credentials.
- OpenRent initial enquiry browser run against a real account.
- Cloudflare tunnel and Vercel environment verification.
- Corpus Number Capture Handoff audit against live/recent conversations.
- Queue scheduling for future reply checks after 30 minutes and 1 hour.
- Dedicated dead-letter queue view. Current retry metadata exists, but exhausted retry dead-letter handling should be added around RQ failure hooks.
- Full landlord-level dedup by landlord profile across all accounts. Current protection prevents duplicate listing ids and concurrent conversation overlap.

## Deployment Commands

Backend:

```bash
cd openrent-agent
python -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

Worker:

```bash
cd openrent-agent
python scripts/run_workers.py
```

Frontend:

```bash
cd openrent-agent/frontend/dashboard
npm install
npm run build
```

Local frontend dev:

```bash
cd openrent-agent/frontend/dashboard
npm run dev
```

## Restart Order

1. Restart Redis if needed.
2. Restart FastAPI so `init_db()` applies missing columns.
3. Restart RQ workers so new worker/session/proxy logic is loaded.
4. Redeploy or restart frontend.
5. Open Accounts and run manual proxy checks.
6. Start one account worker and watch Workers for heartbeat, job id, phase, and errors.

## Verification Checklist

- `GET /api/health` returns `{"status":"running"}`.
- `GET /api/accounts` returns new proxy/session/worker fields.
- `POST /api/accounts/{id}/check-proxy` persists proxy health.
- `GET /api/proxy-health` shows the same persisted proxy status.
- Starting a worker records `worker_job_id` and `queued`.
- RQ worker transitions account to `running`.
- Heartbeat changes at least every 45 seconds while the worker is active.
- Invalid proxy produces `proxy_error` and Playwright does not launch.
- Valid saved session skips login.
- Expired session relogs in and writes `sessions/account_{id}.json`.
- Captcha or failed auth appears as session/worker error in Accounts.
- Initial outreach only sends during UK allowed hours.
- Initial outreach stops after the daily account limit.
- Leads page shows newly persisted conversations and outbound initial message.
- Logs page shows proxy, login, retry, AI, and worker events.
