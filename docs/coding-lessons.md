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
