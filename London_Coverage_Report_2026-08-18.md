# OpenRent London Coverage & Yield Report

**Generated:** 2026-08-18 (grounded in live prod DB — Supabase Postgres)
**Scope:** All areas the fleet searches, their supply/outreach/lead yield, contention, and the London gaps we are *not* covering.

---

## 1. Executive summary

- **Live fleet:** 16 active accounts — **8 South + 8 North**. (7 old-cohort South accounts — 11, 12, 14, 16, 17, 19 — plus 18 are **benched**, not sending.)
- **Coverage:** 19 South areas + 15 North areas hold active search profiles. But **effective** coverage is thinner than it looks — several areas are held only by *benched* accounts (see §6).
- **Where the leads actually come from:** essentially **100% South**. ~**707 phone-leads all-time**, ~**171 in the last 30d — every one of them South**. North has produced **0 leads** so far (it was only stood up ~1 day ago and is still ramping).
- **Highest-supply South areas:** Woolwich (782/mo), Hanworth (682), Greenwich (564), Upper Norwood (562).
- **Highest-converting South areas (phone-leads):** Hanworth (45/mo), Upper Norwood (39), Greenwich (27), Lewisham (11).
- 🔴 **Biggest problem:** the two best-converting areas — **Hanworth and Greenwich** — currently have **zero live accounts** on them (owned only by benched accounts). High supply + proven conversion, going nowhere.
- 🟡 **North is unproven capacity:** 418 fresh listings/week, 8 accounts, but only 19 messages in 30d and **0 leads**. Big potential, not yet realised.
- **Structural constraint:** we have **more proven high-yield South areas than live South accounts to work them** (11 winners vs 8 accounts). The binding limit is live-account count, not area availability.

---

## 2. Method & honesty notes

- **Measured** (hard data from prod): supply (`listings.first_seen`), outreach (`message_sent` / `last_processed_at`), leads (`conversations.phone_found`), contention (active `search_profiles` per location), rent (`listings.rent_pcm`).
- **"Live" vs "benched":** the DB counts a profile as active regardless of whether the *account* is benched. This report distinguishes **live accounts** {13, 20–34} from **benched** {11, 12, 14, 16, 17, 18, 19}. Benched accounts do not scrape or message, so any area covered only by them is effectively **orphaned**.
- **Estimated / not measured:** yield of areas we do **not** search. OpenRent only exposes listings inside areas we query, so untapped-area numbers in §8 are **market-knowledge estimates, not measured supply** — clearly flagged as such.
- **Radius matters:** each area is a *centroid + radius* (mostly 5 km, some 7–10 km), so named points cover more ground than the labels suggest. Gap analysis accounts for this.

---

## 3. Regional coverage summary

| Region | Live accts | Active areas | New listings/wk | New/30d | Msgs/30d | Leads/30d | Leads all-time |
|--------|-----------|--------------|-----------------|---------|----------|-----------|----------------|
| **South** | 8 | 19 | ~956 | 2,588 | 546 | ~171 | ~707 |
| **North** | 8 | 15 | ~418 | 418* | 19 | 0 | 0 |

\* North areas were created ~2026-08-17, so its 30-day and 7-day figures are the same — it has barely one cycle of history.

**Read:** South is the entire lead engine. North is fresh capacity that has not yet converted — the next 1–2 weeks decide whether it earns its 8 accounts.

---

## 4. Full covered-area table

### South (ordered by monthly supply)

| Area | Live/total accts | New/wk | New/30d | Msgs/30d | Leads 30d | Leads all-time | Uncontacted now | Avg rent |
|------|------------------|--------|---------|----------|-----------|----------------|-----------------|----------|
| Woolwich | **3**/6 | 150 | 782 | 175 | 7 | 21 | 121 | £2,233 |
| Hanworth¹ | **0**/2 | 139 | 682 | 155 | 45 | 105 | 13 | £2,039 |
| Greenwich | **0**/3 | 83 | 564 | 147 | 27 | 106 | 57 | £2,286 |
| Upper Norwood | **1**/5 | 57 | 562 | 131 | 39 | 100 | 42 | £2,073 |
| Peckham | 2/2 | 163 | 263 | 60 | 9 | 26 | 4 | £2,646 |
| Lewisham | **1**/4 | 122 | 211 | 47 | 11 | 87 | 56 | £2,206 |
| Wandsworth | 2/2 | 127 | 209 | 60 | 5 | 28 | 46 | £2,578 |
| Tooting | 2/2 | 64 | 146 | 45 | 5 | 19 | 11 | £2,396 |
| Kingston | **1**/3 | 53 | 143 | 23 | 1 | 68 | 42 | £2,172 |
| Clapham | 2/2 | 141 | 141 | 21 | 5 | 6 | 65 | £2,884 |
| Bexleyheath | 2/3 | 64 | 128 | 27 | 5 | 84 | 43 | £1,999 |
| Sutton | 1/1 | 39 | 39 | 11 | 3 | 14 | 3 | £2,248 |
| Bexley | **0**/1 | 12 | 38 | 8 | 1 | 5 | 6 | £1,588 |
| Purley | 1/1 | 36 | 36 | 5 | 2 | 12 | 6 | £1,840 |
| Croydon | 1/1 | 28 | 28 | 4 | 3 | 3 | 6 | £1,766 |
| Bromley | 1/1 | 14 | 16 | 8 | 1 | 5 | 0 | £2,044 |
| Mitcham | 1/1 | 15 | 15 | 4 | 1 | 11 | 1 | £2,110 |
| Green St Green | 1/1 | 7 | 7 | 4 | 1 | 4 | 0 | £2,100 |
| Sidcup | 1/1 | 3 | 3 | 1 | 0 | 3 | 0 | £1,825 |

¹ *Hanworth is tagged region=South but is geographically **West London** (Feltham/Hounslow/Twickenham, TW postcodes). It is our single best-converting area.*

### North (all live accounts; freshly stood up ~2026-08-17)

| Area | Accts | New/wk | Msgs/30d | Leads | Uncontacted now | Avg rent |
|------|-------|--------|----------|-------|-----------------|----------|
| Wood Green | 2 | 75 | 3 | 0 | 52 | £2,498 |
| Bow | 2 | 50 | 3 | 0 | 44 | £3,338 |
| Acton | 2 | 50 | 1 | 0 | 42 | £1,850 |
| Leytonstone | 2 | 44 | 4 | 0 | 30 | £3,363 |
| Stratford | 2 | 34 | 1 | 0 | 30 | £2,200 |
| Tottenham | 2 | 30 | 1 | 0 | 26 | £3,400 |
| Edmonton | 1 | 26 | 1 | 0 | 23 | £3,600 |
| Ealing | 1 | 25 | 1 | 0 | 23 | £2,300 |
| Leyton | 2 | 25 | 0 | 0 | 25 | — |
| Finsbury Park | 1 | 20 | 1 | 0 | 0 | £2,350 |
| Enfield | 2 | 20 | 2 | 0 | 9 | £2,650 |
| Walthamstow | 2 | 11 | 0 | 0 | 11 | — |
| Barking | 1 | 8 | 1 | 0 | 3 | £2,100 |
| Ilford | 1 | 1 | 0 | 0 | 0 | — |
| Hackney | 1 | 0 | 0 | 0 | 0 | — |

**North observations:** ~380 uncontacted listings sitting claimable right now but almost no outreach yet (19 msgs/30d) — workers are just starting. Several North areas skew expensive (Edmonton £3,600, Tottenham £3,400, Leytonstone £3,363, Bow £3,338 avg) which may push stock above persona affordability bands — worth watching claim rates. Ilford/Hackney are near-dry and candidates to replace once North proves out.

---

## 5. Highest-yield ranking

**By raw supply (new listings / month):**
1. Woolwich 782 · 2. Hanworth 682 · 3. Greenwich 564 · 4. Upper Norwood 562 · 5. Peckham 263 · 6. Lewisham 211 · 7. Wandsworth 209

**By actual conversion (phone-leads / month) — the metric that matters:**
1. **Hanworth 45** · 2. **Upper Norwood 39** · 3. **Greenwich 27** · 4. Lewisham 11 · 5. Peckham 9 · 6. Woolwich 7 · 7. Bexleyheath / Clapham / Tooting / Wandsworth 5

**Insight:** supply ≠ conversion. Woolwich has the most listings but converts poorly (7 leads/mo on 175 msgs). Hanworth, Upper Norwood, Greenwich convert 3–6× better per message. **~78% of all-time leads come from just 6 areas:** Hanworth, Greenwich, Upper Norwood, Lewisham, Bexleyheath, Kingston (~550 of 707).

---

## 6. 🔴 Critical gaps *inside* current coverage (orphaned high-yield areas)

These areas have strong supply and proven conversion but **no live account working them** — they are covered only on paper by benched accounts:

| Orphaned area | New/wk | Leads all-time | Uncontacted now | Held only by (benched) |
|---------------|--------|----------------|-----------------|------------------------|
| **Hanworth** | 139 | 105 (our #1 converter) | 13 | 14, 17 |
| **Greenwich** | 83 | 106 (our #2 converter) | 57 | 11, 14, 19 |
| **Bexley** | 12 | 5 | 6 | 11 |

Also **thinly covered** (only 1 live account on a proven area): Upper Norwood (1 of 5), Lewisham (1 of 4), Kingston (1 of 3).

> Note: the 33→SW rebalance earlier today improved accounts 28/33 individually, but moving 33 off Greenwich left Greenwich with no live account. Net-net the fleet has **more proven winners than live South accounts to cover them.**

**This is the single highest-leverage fix:** put a healthy live account back on Hanworth and Greenwich.

---

## 7. North status: capacity parked, not yet earning

- 8 accounts, 15 areas, ~418 fresh listings/week — real supply exists.
- But **19 messages in 30 days and 0 leads.** Causes: areas only ~1 day old, two accounts (22, 24) were on the now-replaced bad proxies, workers still ramping.
- **Verdict:** don't judge North yet. Re-measure in 7–14 days. If leads stay near zero while South starves for accounts, the strategic question is whether 8 accounts belong in North at all, or whether some should return South to cover the orphaned winners.

---

## 8. Untapped London areas (NOT covered)

⚠️ **Estimates, not measured** — these are known high-density rental markets we don't currently search. Supply figures are market-knowledge guesses. Radius overlap from neighbouring covered areas is noted where relevant.

**South-West (our best-converting cluster — expand here first):**
- **Brixton, Streatham, Balham** — dense, high-demand, sit between Clapham/Tooting/Upper Norwood (partly within 5 km radius, but centroids uncovered). Strong candidates; adjacent to proven converters.
- **Putney, Wimbledon, Morden, Raynes Park** — Wimbledon is already a configured-but-unused South location (0 listings pulled — never activated). Putney partly caught by Wandsworth radius.

**South-East (proven converter cluster):**
- **Deptford, New Cross, Camberwell** — inner SE, likely partly inside Peckham/Greenwich/Lewisham radii but worth explicit centroids given conversion strength here.
- **Catford, Forest Hill, Sydenham, Beckenham** — SE gap south of Lewisham.
- **Orpington, Chislehurst, Petts Wood** — outer SE gap beyond Bromley/Sidcup.
- **Thamesmead, Abbey Wood, Plumstead** — likely inside Woolwich radius; low priority.

**West (uncovered corridor between Wandsworth and Acton):**
- **Fulham, Hammersmith, Chiswick, Shepherd's Bush** — genuine gap, high rents (may exceed persona bands — screen against affordability first).
- **Richmond, Twickenham, Feltham** — largely covered by Hanworth/Kingston radius.

**North / North-West (thin fleet knowledge, unproven):**
- **Islington, Camden, Holloway, Highbury** — inner-north gap between Finsbury Park and Hackney; high demand.
- **Wembley, Harrow, Barnet, Finchley, Hendon, Golders Green** — outer NW/N, entirely uncovered.

**East (beyond current E-London ring):**
- **Bethnal Green, Whitechapel, Poplar, Canary Wharf** — inner-east gap between Bow and the City (Poplar/Canary Wharf partly in Bow radius).
- **Romford, Hornchurch, Dagenham, Upminster** — outer-east, uncovered.

**Priority recommendation for untapped expansion:** stay adjacent to what already converts — **Brixton / Streatham / Balham (SW)** and **Catford / Forest Hill / New Cross (SE)** are the highest-confidence bets because they neighbour our top-converting areas.

---

## 9. Deliberately excluded (do not re-enable)

These carry huge historical supply but were **correctly de-allocated** on 2026-08-17 — they are Home-Counties, not London, and were the source of the earlier 50% wasted effort:

| Area | Historical supply | Status |
|------|-------------------|--------|
| Brentwood (South Park Cottages) | 751 | de-allocated ✅ |
| Borehamwood (Kingsley Ave) | 707 | de-allocated ✅ |
| Chigwell (Chester Rd) | 595 | de-allocated ✅ |
| Roydon/Harlow, Welwyn, Wooburn Green, Berkhamsted, Great Missenden, Ongar, Epping Forest | 48–244 each | de-allocated ✅ |

*(All tagged region=North in the DB, but they are Herts/Essex/Bucks — a mislabel, harmless since they're non-allocatable.)* Legacy non-London test areas (Birmingham, Manchester, Leeds, Leicester) also appear in history — out of scope.

---

## 10. Recommendations (prioritised)

1. **Re-man the orphaned winners (highest leverage).** Assign a live account to **Hanworth** and **Greenwich** — together ~211 all-time leads, currently zero live coverage. Cheapest, fastest lead recovery available.
2. **Reinforce thin high-converters.** Upper Norwood, Lewisham, Kingston each have only 1 live account on proven-converting supply — add a second.
3. **Fix the account bottleneck.** The limiter is 8 live South accounts vs 11 proven winners. Revive or replace the 7 benched South-cohort accounts (11/12/14/16/17/19) — see the degraded-account work. This unlocks everything above.
4. **Give North 1–2 weeks, then decide.** If North stays at ~0 leads while South is account-starved, rebalance some North accounts back to the orphaned South winners.
5. **Expand adjacent, not random.** First new areas should be **Brixton/Streatham/Balham** (SW) and **Catford/Forest Hill/New Cross** (SE) — neighbours of our best converters. Activate the already-configured **Wimbledon** while at it.
6. **Screen West/expensive areas for affordability** before adding (Fulham/Hammersmith/Chiswick and several North areas average £3,300–3,600, above some persona bands).

---

*Numbers are point-in-time (2026-08-18). Supply/lead figures for covered areas are measured; untapped-area figures in §8 are market estimates. Re-run the coverage query to refresh.*
