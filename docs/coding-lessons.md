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
