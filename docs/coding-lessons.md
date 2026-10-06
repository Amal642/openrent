# Coding Lessons

A living pre-flight checklist + project gotchas so mistakes don't repeat.
Loaded on demand (not every turn) — keep it lean: **one line per lesson, prune duplicates.**

## How to use
- **Before** any coding or deploy task: skim the pre-flight checklist and the gotchas relevant to what you're touching.
- **After** any mistake, wrong assumption, or user correction: append ONE line under the right section. Format: `- <rule, as an imperative> [YYYY-MM-DD]`.
- This complements auto-memory: memory = project facts; this file = *process/verification* lessons ("verify X before doing Y").

## Pre-flight checklist (run before editing / deploying)
1. **Verify the runtime target before changing it.** Confirm where a thing is actually served/run from *before* editing or rebuilding it — don't assume prod == the box you SSH'd into.
2. **Verify a metric means what you think before acting on it.** Check the filters/exclusions behind a number before you build a decision on it.
3. **Make prod changes reversible.** Snapshot first → apply → measure. Don't churn irreversibly; prefer `--dry-run` for bulk/DB changes.
4. **Know the deploy mechanism before deploying.** git-push auto-deploy vs `patch`/`git apply` vs manual CLI — confirm which, then act.
5. **Don't over-churn.** If unsure, gather the data first and change once; avoid repeated re-does of the same prod state in one session.

## Project gotchas (living list)
- Dashboard frontend is hosted **externally** (Vercel/CF Pages, auto-deploys on push to `main`); the Hetzner box only serves the API (uvicorn :8000 via cloudflared). Never rebuild the frontend on prod to change the live UI. [2026-09-22]
- Area **supply numbers are ~65% estate agents / short-lets** — use *contactable* supply (~4/day/area). One account (daily_limit 8) already harvests an area; doubling owners is usually redundant (verify contactable, not raw, before allocating). [2026-09-22]
- prod git root is the **parent** dir, so `git apply` silently no-ops — use `patch -p2`/`-p1` from the app dir. [2026-09-14]
- Never use a naive `"captcha" in html` check — OpenRent's site-wide reCAPTCHA breaks it; match the real challenge text. [2026-09-21]
- Search-profile changes are read fresh per run — **no worker restart needed**; restarting mid-run risks orphaned workers. [2026-09-17]
- **Don't `ALTER` a hot table** (e.g. `accounts`) on the live Supabase DB — the workers/backend hold constant locks, so `ADD COLUMN` fails with lock/statement-timeout. Prefer a **logic-only fix** (no schema change), or stop the services for the DDL window. [2026-09-23]
- Prefer fixing detector/allocator logic over adding DB columns — e.g. the degraded detector judges only **active-profile** conversations (a reallocated account's stale-area convos drop out naturally), giving a grace period with zero schema change. [2026-09-23]
- In prompts, mentioning a behaviour ("some landlords ask for X; never volunteer it") still primes the model to offer X. Phrase reactive facts as "only if explicitly asked, otherwise never mention", and grep live outbound for the phrase after shipping. [2026-09-28]
- Local pytest needs `OPENAI_API_KEY` set to any dummy value (e.g. `sk-test`), otherwise the WhatsApp test modules fail at collection. `test_advisor` fails locally because there is no `search_profiles` table (env, not a regression). [2026-09-29]
- OpenRent now also serves an **AWS WAF CAPTCHA** (title "Human Verification", `#captcha-container`, `awsWaf`); `_is_bot_page` misses it, so a challenged discovery page logs `DISCOVERY_ZERO_CANDIDATES` instead of `DISCOVERY_BOT_WALL`. Treat zero-candidate spikes as possible WAF blocks. [2026-09-28]
- Never `pkill -f <pattern>` inside an `ssh '...'` command when the pattern appears in that same command line — it kills its own SSH session (exit 255). [2026-09-28]
- Before any manual area/profile change, check the **06:00 UTC `run_sim_allocator.py` cron** (it rewrites search_profiles daily; it caused Welwyn + 3 double-ups on 2026-09-26/28) and run it with `--dry-run` after your change to prove it won't undo it. [2026-09-28]
- Run prod one-off scripts with `PYTHONPATH=/opt/openrent-agent/openrent-agent` (the venv has no app package installed); plain `venv/bin/python patches/x.py` fails with ModuleNotFoundError. [2026-09-29]
- Before configuring Kapso in the UI, confirm the logged-in project is the one prod's `KAPSO_API_KEY` belongs to (compare phone-number config IDs via the API vs the UI) — prod's key is in a DIFFERENT Kapso project/account than bricbybrictech's "OpenRent" project, so UI webhooks/sessions and API sends don't see each other. [2026-09-29]
- A listing's owning account is resolved ONLY via `listing.search_profile_id -> account` (conversations have no account_id); any cross-account listing sharing must move `search_profile_id` to the sender's ACTIVE profile (degraded detector judges active profiles only) and re-check the persona price cap once rent is known. [2026-09-30]
- `tests/test_db_repository.py::test_save_phone_number_does_not_queue_non_london_sheet_export` fails on prod's venv PRE-EXISTING (passes locally) — don't treat it as a regression. [2026-09-30]
- `app.db.repository.session_scope()` does NOT auto-commit — one-off prod writes must call `s.commit()` explicitly, then re-query to verify (a silent no-op looked like success on 2026-09-30). [2026-09-30]
- Live OpenRent threads label OUR messages `sender="us"` (inbox.extract_conversation); every "sent by us" check must use `personas.TENANT_SENDERS` — sets without "us" silently disabled the give-out shortcut for months while monkeypatched tests passed. [2026-09-30]
- Before acting on an audit/reviewer "High" finding, measure it on prod data first — on 2026-09-30 two "High" outreach bugs had 0-1 real occurrences in 14 days while a "Medium" (6-month tenancy skip) cost ~15 listings/day. [2026-09-30]
- Prod's copy of a TEST file can be stale (tests aren't always deployed with code): 5 `tests/test_whatsapp_matching.py` failures on prod were a stale test file, not a regression. Before blaming prod, md5-compare the test file with HEAD. [2026-10-01]
- Before re-running a matcher/linker by hand, confirm the function is DB-only (e.g. `apply_match_result` writes + enqueues the sheet, sends nothing); never call the full inbound handler just to re-match. [2026-09-30]
- For a fragile LLM case (e.g. "is this Sarah?" -> "I'm Sarah's partner"), detect it in code and hand the model the exact words; a quoted example phrase in the general prompt gets over-applied to cases where it doesn't fit. Sample the real model 5-8x per scenario before deploying any prompt change. [2026-09-30]
- 5 `tests/test_prompt_persona_flow.py` tests fail on prod only because prod `.env` has `HUMAN_REPLY_PROMPT=all`; run them with `HUMAN_REPLY_PROMPT=0` to validate the legacy prompt path. [2026-09-30]
- Any new externally-called endpoint (webhooks) must be added to the `is_public` set in `CRMAuthMiddleware` (app/api/main.py), else it 401s before reaching its own signature check; smoke-test it through `TestClient(app)`, not just the handler function. [2026-10-01]
- `record_handoff_intent` REUSES an existing unconsumed intent, so re-sharing the number in the same thread does NOT restart the matcher's 7-day window; after any manual/bulk re-share, refresh `created_at` (or fix the function to do it). [2026-10-02]
- WhatsApp matcher scoring is load-bearing: before deploying ANY score/blend change, run the old-vs-new evidence-only comparison over all prod whatsapp_contacts (plus consumed handoff intents) and require zero lost stored matches; 2 of 4 plausible tweaks on 2026-10-02 broke 5-10 correct matches. [2026-10-02]
- Prod can lag HEAD by whole commits (4191a0c, Sep 30, never deployed): before a deploy, diff prod vs HEAD for every touched file and ship only your own hunks via `patch` (dry-run first); never copy whole files over. [2026-10-03]
- Don't state behavioural "facts" (e.g. "late-night enquiries get fewer replies") without querying the data first; the 22:00 reply rate was 85%, same as daytime. [2026-10-03]
- search_profiles.area is an OpenRent radius in KM (area=10 → "Within 10 km"), not miles; 36 r10 circles overlap ~7x so area labels are nominal (2026-10-03).
- Bare hyphenated number pairs in chat ('6-7pm', '4-5 hours', '9-11am') are time ranges, not dd-mm dates; date regexes must require a year for hyphen dates and not read a clock time after a month name. Replay every stored viewing old-vs-new before deploying any date-parser change. [2026-10-03]
- Prompts embed the current UK time (current_uk_datetime_line), so before/after prompt fingerprints differ run-to-run; freeze it (patches/persona_prompt_snapshot.py) when proving a deploy leaves legacy prompts byte-identical. New Account columns also need local `init_db()` on the dev sqlite or test_advisor fails. [2026-10-06]
- The 06:00 sim_allocator read a 1-day-old area as 'exhausted' (7-day supply ~0) and its metrics didn't count an owner assigned that day, so it moved acct 40 onto acct 39's area; it now uses search_profiles for ownership and skips accounts inside a 7-day grace. After provisioning, always dry-run the allocator and check the 06:00 log next morning. [2026-10-06]
