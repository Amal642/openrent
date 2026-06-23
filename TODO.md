# OpenRent Operations and Area Intelligence TODO

Last updated: 2026-06-22

## Current production state (as of 2026-06-22 evening)

### Account and profile state
- All 7 active accounts now have search profiles and are sending.
- Max daily capacity: 56 messages/day (7 accounts × 8/day).
- Proxies healthy across all accounts: proxy_status=ok, proxy_failures=0.
- Processing failure root cause identified and fixed (see below).

### Active coverage — South London only
| Account | Email | Sender | Area | Radius |
|---|---|---|---|---|
| 11 | mooncrest2026 | Aisha | Upper Norwood, London | 11mi |
| 12 | wavehub2026 | Amelia | Kingston Upon Thames | 10mi |
| 13 | cloudhaven2027 | Alex | Bexleyheath, Greater London | 10mi |
| 14 | citybloom2026 | (correct) | Hanworth, London | 11mi |
| 16 | riverstone2027 | Maya | Lewisham, London | 10mi (new) |
| 18 | silverwind2026 | Priya | Croydon, Greater London | 10mi (new) |
| 19 | upperwind2027 | Hannah | Woolwich, Greater London | 10mi (new) |


### Phone capture rate by area (all-time)
- Woolwich, Greater London (10mi): **40% phone rate** — best performing.
- Bexleyheath, Greater London (10mi): **30% phone rate**.
- Kingston Upon Thames (10mi): 20% phone rate.
- Sidcup, Greater London (10mi): 18.8% phone rate.
- Hanworth, London (11mi): 13.3% phone rate.
- Upper Norwood, London (11mi): 11.5% phone rate.
- Lewisham, Croydon: new — no data yet.

### Processing failure fix (deployed 2026-06-22)
- Root cause: transient proxy tunnel errors (`ERR_TUNNEL_CONNECTION_FAILED`) hit the broad `except Exception` in `process_listings.py`, permanently marking listings as failed with no reason stored.
- **Fix deployed**: `fail_reason` column added to listings table. All 3 call sites in `process_listings.py` now store a reason string. Exception path stores `ExcType: message[:300]` so tunnel errors are now queryable.
- **Proxy recovery fix deployed**: `reset_failed_listings_for_account()` called in `proxy_health_monitor.py` on both proxy recovery and proxy reassignment paths — failed listings auto-reset when proxy heals.
- **329 existing failed listings manually reset** on 2026-06-22 after confirming all proxies healthy.

### Persona and name issues
- All couple persona templates are correct: female `primary` (sender), male `partner`.
- **Account 19 fixed (2026-06-22)**: was Oliver/Hannah → now Hannah/Oliver. Zero conversations, safe.
- **Account 12 still inverted**: Oliver sending, Amelia is partner. Has 7 live convos, 1 viewing thread. Fix after threads settle.
- **Account 13 still inverted**: Michael sending, Alex as partner (also male pool). Has 21 live convos, 6 viewing threads. Needs a fresh female name (Charlotte, Rebecca, Victoria, or Claire) — simple swap insufficient as both names are male. Fix after viewing threads close (~2026-06-25).
- Name pool size (4 names per role per template) is too small — causes duplicates on pool exhaustion.

### Duplicate names across accounts
- Daniel: 4 accounts (6, 7, 14, 18)
- Aisha: 3 accounts (7, 9, 11)
- Alex: 3 accounts (8, 13, 17)
- Oliver: 2 accounts (12, 19 — 19 fixed, now partner not sender)
- Michael: 2 accounts (13, 17)
- Leah: 2 accounts (6, 10)
- Sam: 2 accounts (9, 10)


## Immediate operational TODO

### Persona name fixes (accounts 12 and 13)
- [x] ~~Account 12~~: DB and OpenRent both show Amelia. Fixed.
- [x] ~~Account 13~~: Keeping "Alex" permanently. Every active conversation already mentions "Alex" and new ones start continuously — pausing the account to do a clean cut would cost ~100+ outbound messages with no landlord-facing benefit. Alex is gender-neutral and the account is performing (phone captured).
- [x] ~~Expand name pools in `app/ai/personas.py` from 4 to 8 names per role per template.~~

### Other
- [ ] Verify outreach only consumes listings from active search profiles.
- [ ] Decide the intended outreach pacing:
  - Current: one initial message every 1–3 hours per productive account.
  - Confirm whether the goal is natural pacing or reliably reaching eight messages per account per day.
- [ ] Add an account readiness indicator that distinguishes:
  - Enabled / has active profile / has usable inventory / healthy session / healthy proxy / outreach due
- [ ] Display a clear reason when an enabled account sends zero messages.


## A/B experiment TODO

- [x] Log phone captures immediately after the authoritative database write.
- [x] Use `conversations.phone_found_at` as the capture source of truth.
- [x] Exclude conversations with prior AI replies, phone captures, or phone requests.
- [x] Assign an experiment arm only before the first controlled reply.
- [ ] Count only assignments created after the clean-enrollment deployment.
- [ ] Run the frozen live-grader audit on the new transcript distribution.
- [ ] Continue until approximately 280 eligible leads per arm.
- [ ] Keep the locked decision bar: B − A ≥ +10 percentage points and the one-sided confidence interval excludes zero.
- [ ] Discuss and decide the remaining behavioral changes:
  - Ask for the number after a concrete viewing is agreed.
  - Stop after a clear refusal.
  - Handle reciprocal number requests consistently.
  - Validate names, locations, dates, and viewing type before sending.
  - Review automatic viewing cancellations.


## Area Intelligence: required capabilities

Create a shared market-intelligence layer that is separate from sending accounts.

### Data to collect by area

- [ ] Total listings discovered.
- [ ] New listings per day.
- [ ] Unique listings after deduplication.
- [ ] Private-landlord listings.
- [ ] Agent listings.
- [ ] Contactable listings.
- [ ] Not-contactable listings.
- [ ] Previously contacted listings.
- [ ] Processing failures and failure reasons.
- [ ] Currently usable inventory.
- [ ] Inventory age and exhaustion rate.
- [ ] Reply rate.
- [ ] Viewing-booking rate.
- [ ] Phone-capture rate.
- [ ] Qualified phone-capture rate.
- [ ] Scam reports, refusals, blocks, and other safety signals.

### Area scoring

- [ ] Define a deterministic score based on:
  - Usable new listings per day
  - Private-landlord percentage
  - Contactability percentage
  - Reply rate
  - Qualified phone-capture rate
  - Inventory exhaustion rate
  - Safety/account-risk signals
- [ ] Do not let an AI model invent metrics or scores.
- [ ] Use AI only to explain the measured data and recommend actions.
- [ ] Mark areas as `expand`, `maintain`, `pause`, or `insufficient data`.

### Capacity recommendations

- [ ] Calculate realistic messages per productive account per day.
- [ ] Estimate how many sending accounts each area can support.
- [ ] Recommend account allocation by area.
- [ ] Add 15–20% spare account capacity for session, proxy, and account failures.
- [ ] Do not recommend new SIMs, accounts, or proxies unless measured listing supply supports them.


## Discovery architecture

- [ ] Separate central market discovery from account-specific outreach.
- [ ] Maintain one shared, deduplicated listing inventory.
- [ ] Store the area, first-seen time, last-seen time, listing status, landlord type, and contactability.
- [ ] Refresh active areas on a controlled schedule.
- [ ] Archive or expire stale listings.
- [ ] Ensure discovery accounts/identities are separate from messaging accounts.
- [ ] Start with a small discovery proxy pool rather than one proxy per monitored area.


## Proxy and cost controls

- [ ] Measure proxy bandwidth and request volume before expanding discovery.
- [ ] Use approximately 1–3 discovery workers/proxies for the initial area monitor.
- [ ] Keep dedicated or isolated proxies for sending accounts where required.
- [ ] Track monthly proxy cost per productive account and per qualified phone lead.
- [ ] Track session expiry, captcha, login failure, and restriction rates by proxy/provider.
- [ ] Avoid provisioning one proxy for every area being monitored.
- [ ] Review 7–14 days of area-supply data before buying additional SIMs or proxies.


## Dashboard and advisory interface

- [ ] Add an Area Intelligence page.
- [ ] Show area supply, usable inventory, conversion rates, and trend charts.
- [ ] Show account-to-area allocation.
- [ ] Show accounts enabled without profiles or inventory.
- [ ] Show recommended areas and the evidence behind each recommendation.
- [ ] Allow questions such as:
  - Which areas should we focus on this week?
  - Which areas are exhausted?
  - How many accounts can this area support?
  - Where should the next account be assigned?
  - How many additional SIMs/proxies are justified?


## Recommended next sequence

1. [x] ~~Restore South London coverage: reactivate Kingston 10mi (acct 12), Bexleyheath 10mi (acct 13).~~
2. [x] ~~Fix persona name inversion on account 19.~~
3. [x] ~~Assign profiles to accounts 16, 18, 19 (Lewisham, Croydon, Woolwich).~~
4. [x] ~~Investigate and fix the ~45% processing failure rate — fail_reason column + proxy recovery reset deployed.~~
5. [x] ~~Fix persona name inversions on accounts 12 and 13~~ — Amelia fixed on 12; Alex kept on 13 (gender-neutral, all threads exposed, not worth pausing).
6. [x] ~~Expand name pools in personas.py (4 → 8 per role).~~
7. [ ] Monitor Lewisham, Croydon, Woolwich for 7–14 days to establish phone rate baselines.
8. [ ] Add reliable per-area supply and usability metrics.
9. [ ] Add deterministic area scoring and saturation reporting.
10. [ ] Add account, SIM, and proxy capacity recommendations.
11. [ ] Add the conversational AI adviser over the verified metrics.
12. [ ] Provision additional sending infrastructure only after the data justifies it.
