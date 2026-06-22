# OpenRent Operations and Area Intelligence TODO

Last updated: 2026-06-22

## Current production findings

### Account and profile state
- Seven accounts are enabled, but only four have active search profiles.
- Accounts 16, 18, and 19 have no search profile, so they cannot discover or contact listings.
- Accounts 11 (Upper Norwood) and 14 (Hanworth) currently provide most new outreach.
- New outreach is intentionally limited to one message per account every 1–3 hours.
- The daily limit of eight is a maximum, not a quota the scheduler guarantees it will fill.
- Sessions and proxies were healthy during the audit; they were not the main throughput bottleneck.

### South London coverage — profile swap broke the design
- The original design was correct: 4 accounts with large radii, zero listing overlap, covering South London.
- Accounts 12 and 13 had their productive large-radius profiles **replaced** with much smaller ones at some point. This is the root cause of their inventory exhaustion.
- Account 12 was **Kingston Upon Thames 10mi** (SW London). It is now **Green Street Green 4mi** — only 11 listings ever discovered.
- Account 13 was **Bexleyheath 10mi** (SE London, 30% phone rate, 125 listings). It is now **Bexley 6mi** — only 38 listings ever discovered.
- The inactive profiles (Kingston 10mi, Bexleyheath 10mi) have avail=0 only because they have not been scraped since deactivation. New listings in those areas are waiting to be discovered.
- Increasing scroll depth in the scraper is not the bottleneck. The scraper already discovers 300+ listings per run in active large-radius profiles.

### Agent listings and processing failures
- ~35–76% of discovered listings per area are agent listings and are correctly skipped.
- ~45% of private-landlord listings fail processing (processing_failed=true). This is a major drain on contactable inventory and worth investigating.
- 292 listings across active profiles are skipped as agents.

### Phone capture rate by area (all-time, from live data)
- Woolwich, Greater London (inactive, 10mi): **40% phone rate** — best performing South London area.
- Bexleyheath, Greater London (inactive, 10mi): **30% phone rate**.
- Sidcup, Greater London (inactive, 10mi): 18.8% phone rate.
- Kingston Upon Thames (inactive, 10mi): 20% phone rate.
- Hanworth, London (active, 11mi): 13.3% phone rate.
- Upper Norwood, London (active, 11mi): 11.5% phone rate.
- The two currently active London areas have the lowest phone rates of any area ever run.

### Daily outreach trend
- Peak was 39 messages/day on 2026-06-15; has been declining as inventory depletes.
- As of 2026-06-22: 4 messages sent (day still in progress).
- Phone captures track outreach: 2–7/day when outreach was healthy, down to 2 today.

### Persona and name issues
- All couple persona templates are designed correctly: female name is `primary` (the sender), male name is `partner`. The wife is supposed to be texting.
- **3 of 7 active accounts have the husband texting** because the DB assignment is inverted — likely caused by name pool exhaustion during setup:
  - Account 12 (wavehub2026): **Oliver** sending — Oliver is a male partner-pool name.
  - Account 13 (cloudhaven2027): **Michael** sending — Michael is a male partner-pool name.
  - Account 19 (upperwind2027): **Oliver** sending — same issue.
- Account 13 also has **Alex** as the partner name, which is also from the male partner pool for `engineer_consultant_couple`. Even after swapping, neither name is clearly female. Account 13 needs a proper female primary name (Charlotte, Rebecca, Victoria, or Claire).
- Account 13 has **multiple live VIEWING_DISCUSSION conversations** as of 2026-06-22. Do not swap its names until those threads close (allow 2–3 days).
- Account 12 has one potentially live VIEWING_DISCUSSION thread (44514537, last inbound 2026-06-19). Low but real risk to swap now.
- Account 19 has **zero conversations and no profile** — name swap is completely safe immediately.
- The prompts in `prompts.py:280` and `prompts.py:299` correctly say "my husband is handling the viewing coordination" — but this only makes sense when a female persona is the sender. On accounts 12, 13, 19 it produces a male persona saying "my husband", which is incoherent.
- Name pool size (4 names per role per template) is too small for the number of accounts. When the pool is exhausted, `materialize_persona` falls back to reusing names.

### Duplicate names across accounts
- Daniel: 4 accounts (6, 7, 14, 18)
- Aisha: 3 accounts (7, 9, 11)
- Alex: 3 accounts (8, 13, 17)
- Oliver: 2 accounts (12, 19)
- Michael: 2 accounts (13, 17)
- Leah: 2 accounts (6, 10)
- Sam: 2 accounts (9, 10)


## Immediate operational TODO

### Highest priority — restore South London coverage (biggest volume impact)
- [ ] **Account 12**: Deactivate Green Street Green 4mi. Reactivate Kingston Upon Thames 10mi (profile ID 8). Restores SW London coverage and triggers fresh scrape of an under-exploited area.
- [ ] **Account 13**: Deactivate Bexley 6mi. Reactivate Bexleyheath 10mi (profile ID 7). Restores SE London coverage (30% phone rate, 125 listings when previously active). Do this after live conversations settle (~2026-06-25).
- [ ] **Account 11**: Reactivate Woolwich 10mi (profile ID 10) alongside Upper Norwood. Best phone rate at 40%.
- [ ] Assign South London profiles to accounts **16, 18, and 19**. These accounts are fully idle. Each adds up to 8 messages/day. Proven South London corridors: Eltham, Lewisham, Bromley (town centre), Catford for SE; Morden, Mitcham, Tooting for south-central.

### Persona name fixes
- [ ] **Account 19**: Swap `persona_name` ↔ `persona_partner_name` and `persona_job` ↔ `persona_partner_job` in the DB. Safe to do immediately (zero conversations).
- [ ] **Account 12**: Same swap. Do after thread 44514537 closes or goes cold.
- [ ] **Account 13**: Assign a proper female primary name (Charlotte, Rebecca, Victoria, or Claire) from the `engineer_consultant_couple` template. Simple swap is insufficient — both current names are from the male partner pool. Do after live VIEWING_DISCUSSION threads close (~2026-06-25).
- [ ] Expand name pools in `app/ai/personas.py` from 4 to at least 8–10 names per role per template to prevent future pool exhaustion and duplicate reuse.

### Other
- [ ] Investigate why ~45% of private-landlord listings fail processing (`processing_failed=true`). Fixing this would roughly double contactable yield without any new areas or accounts.
- [ ] Verify outreach only consumes listings from active search profiles.
- [ ] Decide the intended outreach pacing:
  - Current: one initial message every 1–3 hours per productive account.
  - Confirm whether the goal is natural pacing or reliably reaching eight messages per account per day.
- [ ] Add an account readiness indicator that distinguishes:
  - Enabled
  - Has active profile
  - Has usable inventory
  - Healthy session
  - Healthy proxy
  - Outreach due
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


## Recommended implementation sequence

1. [ ] Restore South London coverage: reactivate Kingston 10mi (acct 12), Bexleyheath 10mi (acct 13), Woolwich 10mi (acct 11).
2. [ ] Fix persona name inversions on accounts 19 (immediate), 12, and 13 (after live threads close).
3. [ ] Assign profiles to accounts 16, 18, 19 with proven South London areas.
4. [ ] Investigate and fix the ~45% processing failure rate on private-landlord listings.
5. [ ] Add reliable per-area supply and usability metrics.
6. [ ] Collect at least 7–14 days of comparable area data.
7. [ ] Add deterministic area scoring and saturation reporting.
8. [ ] Add account, SIM, and proxy capacity recommendations.
9. [ ] Add the conversational AI adviser over the verified metrics.
10. [ ] Provision additional sending infrastructure only after the data justifies it.
