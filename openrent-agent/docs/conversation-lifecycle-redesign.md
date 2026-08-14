# Conversation Lifecycle Redesign

**Status:** Proposal (pre-implementation)
**Author:** Engineering
**Date:** 2026-08-13
**Scope:** OpenRent on-platform reply loop + WhatsApp channel — the reply → phone-capture → viewing-cancellation lifecycle.

> This document is written against the **running production code** (Supabase Postgres; prod has hot-edits not in git — see deploy notes). Line references are to the prod copies of `scripts/process_replies.py`, `scripts/process_viewing_reminders.py`, `app/whatsapp/*`, `app/ai/*`, `app/db/*`.

---

## 1. Objective (what the system is actually for)

The business goal is **lead generation**, not attending viewings:

- **OpenRent channel:** progress a landlord conversation and **capture the landlord's phone number**. The *"I'm on my way / arriving at 2pm — can I grab a number to coordinate?"* line is an **intentional extraction tactic and must be preserved.**
- **WhatsApp channel:** some landlords are routed to WhatsApp (we hand them our WhatsApp number). We already have *their* number, so the goal there is to **identify which property/lead this is (match) and close politely** in a human way.
- **Both channels:** if a viewing ends up booked, we must **cancel the booking cleanly** — never silently no-show. A no-show is worse than a cancellation because landlords report no-shows.

Everything below serves those goals. The redesign does **not** change the tactics; it fixes the machinery that runs *after* a tactic succeeds, so the system stops cleanly instead of spiralling.

---

## 2. Verified problems (evidence)

All figures below were measured against prod on 2026-08-13 and cross-checked against the code paths.

### P1 — After a phone is captured, the AI keeps replying
There is **no "we already have the number" stop condition**. The only terminal gate is a stage check at `process_replies.py:658` (`HANDOFF_COMPLETE`, `VIEWING_CANCELLED`, `SHORT_TERM_PROPERTY`). Phone capture writes `status = PHONE_ACQUIRED` (the **`status`** column) but leaves **`conversation_stage`** non-terminal, so the thread is not skipped and falls through to `generate_reply()` (~line 1330). There is no `extracted_phone` guard anywhere on that path.

- **47% (174/370)** of recently captured threads sit in a non-terminal stage; **146** have no `viewing_datetime`, so the only auto-terminal path (viewing-cancel) can never fire.
- Corrected severity: post-capture messages are **~62% intended cancellations**; the genuinely gratuitous part is **~65 continuation replies + some of 53 number re-asks**, **concentrated in a tail** of threads that spiral into the live-viewing fiction. That tail is the ban-risk source.
- **Observed example — thread 45253058:** captured the number, stayed `VIEWING_DISCUSSION`, kept replying until the landlord wrote *"Is this an automated response"* and *"you keep sending me the same message."*

### P2 — Cancellation is over-gated, so bookings often never get cancelled → no-shows
Both cancellation paths require the same fragile trio: a parsed `viewing_datetime` **and** stage exactly `VIEWING_BOOKED` **and** the account running inside a narrow 3–5h-before window. Made explicit at `process_viewing_reminders.py:46`:

```python
if not viewing_datetime or not viewing_confirmed or conversation_stage != "VIEWING_BOOKED":
    continue
```

Of **70** no-show-complaint threads: **97%** were `viewing_confirmed`, **51%** never sent any cancellation, **27%** had no datetime, and the 49% that did cancel often cancelled **after** the appointment.

### P3 — The viewing-datetime extractor misses times that are clearly present
Of 120 confirmed-viewing / null-datetime threads, **88% (106)** had a concrete, parseable time in the landlord's message (*"tomorrow's viewing at 5.30pm"*, *"6-6:30pm today"*, *"7:30pm Tue to Thur"*). Only 12% were legitimately vague. So P2's missing datetime is largely an **extractor failure** (`_try_save_viewing_datetime` / `ai_detect_viewing_arranged` / `_parse_ai_viewing_datetime`), not landlords being unclear.

### P4 — Every cancellation leaves a platform-visible footprint
*"You said you are no longer interested in the property"* is OpenRent's **system withdrawal notice**: **48 identical verbatim** occurrences across 50 different landlords, **86%** immediately after our cancellation. Our cancel flow reliably triggers it, and it fires even mid-reschedule (incoherent, landlord-annoying).

### P5 — Three divergent cancellation implementations
Cancellation logic is duplicated across `process_replies.py` (inline), `process_viewing_reminders.py` (backstop), and `app/whatsapp/repository.py:~434` (WhatsApp sweep), with **different guards**. The WhatsApp copy has the *best* fallback (measures from `last_stage_change` when the datetime is stale) — the good logic is in the wrong place and not shared.

### P6 — WhatsApp re-derives identity it already has
WhatsApp matches contacts by fuzzy **name + property** evidence and asks *"which property do you mean?"*. But **23 of 52** incoming WhatsApp numbers are **exactly a landlord number we already captured on OpenRent** (`Conversation.extracted_phone`); ~8 are pre-linkable yet left unmatched, and only 35% of contacts match at all. Match failure also blocks cancellation (you can only cancel a booking you've linked).

> **WhatsApp is not the fire.** 52-contact pilot, **zero** ban/bot/stop signals, and it already has the guards OpenRent lacks (`MAX_REPLIES_REACHED`, `SUSPICIOUS_HOLD`, business-hours pacing, reactive cancel). It should be the *reference*, not dragged along.

### P7 — Persona plausibility (upstream lead loss)
`INCOME_BANDS` is keyed to **persona type, not job** (`personas.py:298`, job list `:227`), so "Teaching Assistant" inherits a £48–64k single income (~£4,667/mo) and gets screened out ("a teaching assistant salary does not pay £4,700/month"). Lower volume, but it kills leads before they reach the capture stage. The "renting in Bristol" origin similarly triggers distance screen-outs.

### P8 — Cross-channel persona/identity strategy is assumed, not enforced
The intended strategy — **the wife messages on OpenRent and hands over the husband's WhatsApp; the husband answers on WhatsApp** (*"my wife handles our OpenRent enquiries"*) — is codified (`personas.py:481` + `generate_phone_share_reply()`; `prompts.py` husband-redirect + last-resort share gating; `app/whatsapp/reply.py:124`). It relies on three invariants that do not hold:

- **P8a — gender not enforced.** The hardcoded *"my husband"* wording assumes a female primary persona, but several template name pools mix genders in the *primary* slot. **4 of 23 active accounts have male/ambiguous primaries** — acct 6 (Daniel), 29 (Michael), 10 (Sam), 13 (Alex). Acct **13 is live** (has a number, highest conversation volume), so it emits *"my husband's WhatsApp"* incoherently, contradicting the WhatsApp side's *"my wife handles OpenRent."*
- **P8b — number coverage.** Only **8 of 23** active accounts have a `mobile_number`; the other **15 (incl. acct 21) cannot route to WhatsApp at all** — the prompt falls back to *"no mobile number is assigned."* The strategy is live on ~35% of the fleet.
- **P8c — one number for the whole fleet.** All **8** mobile-enabled accounts share the **same** WhatsApp number `7599390221`. This is a fleet-wide single point of failure (one block/report kills all WhatsApp routing) **and the root of the P6 match ambiguity** — one number receives enquiries for 8 personas × many listings, so it cannot be resolved to a persona/property by the number alone.

> **Deferred (product, 2026-08-13):** remediation of **P8a (gender-aware wording / female-primary enforcement)** is deferred — do later. The new male-primary cohort (accts 29/30 Michael, 31 Henry+William, 6 Daniel) makes this worse over time but is not blocking. **P8b/P8c (number coverage + distinct-number provisioning) remain a WhatsApp Phase-2 prerequisite.**

### Root-cause summary
| # | Root cause | Type | Status |
|---|---|---|---|
| P1 | No post-capture terminal gate; decisions read `conversation_stage` while capture writes `status` (split-brain) | Code | Proven |
| P2 | Cancellation gated on datetime + exact stage + timing window | Code | Proven |
| P3 | Viewing-datetime extractor misses 88% of stated times | Model/parse | Proven |
| P4 | Cancel flow trips OpenRent withdrawal notice; fires mid-reschedule | Behaviour | Proven |
| P5 | Three divergent cancellation copies | Architecture | Proven |
| P6 | WhatsApp ignores the phone key it already has | Architecture | Proven |
| P7 | Income band keyed to persona type not job | Data | Proven |
| P8 | Wife/husband cross-channel strategy assumed, not enforced: 4/23 male-or-ambiguous personas; only 8/23 have a number; all 8 share one number | Data/architecture | Proven |

---

## 3. Design principles

1. **One canonical state, derived from facts.** Kill the `status` vs `conversation_stage` split-brain. Decisions read a single lifecycle value; `status` remains for UI/telemetry only.
2. **Separate *deciding* from *acting*.** A pure function chooses the next action; only a thin executor touches the browser/WhatsApp. Pure = testable.
3. **Cancellation is an obligation, not a coincidence.** Once a booking exists and we won't attend, we *owe* a cancellation. Discharge it reliably, decoupled from datetime parsing, stage exactness, and account cadence.
4. **Identity is keyed on the phone number.** The same lead is recognised across channels without fuzzy matching.
5. **Reply brains stay channel-specific; lifecycle + cancellation are shared.** OpenRent (capture) and WhatsApp (match/close) have different goals but one lifecycle and one cancellation service.
6. **Preserve the tactics.** The "on my way / number to coordinate" pressure and the persona cover stories are untouched — the fix is purely about *stopping and cancelling correctly*.

---

## 4. Proposed architecture

### 4.1 Canonical lead lifecycle (single source of truth)

Model the meaningful state as one explicit enum derived from facts, oriented around the objective:

```
LEAD ──▶ ENGAGING ──▶ PHONE_CAPTURED ──┬─ (no viewing booked) ─────────────▶ HANDED_OFF   [terminal]
                                        └─ (viewing booked) ─▶ CANCEL_DUE ──▶ CANCELLED     [terminal]
   any state ─▶ DEAD (short-term / duplicate / suspicious / disabled)                      [terminal]
```

- **Terminality is a property of the state**, not an inline set literal.
- `PHONE_CAPTURED` becomes a real, decision-driving state (today capture only writes the `status` column and is invisible to the stop gate).
- Existing string stages map onto this; `status.py` values are retained as display/telemetry labels.

### 4.2 The pure decider — `decide_next_action(facts) -> Action`

- **Input:** a plain snapshot, no I/O — `has_phone`, `viewing_confirmed`, `viewing_datetime`, `cancellation_sent_at`, `cancellation_due_at`, `phone_requested_at`, `last_landlord_message`, `last_outbound`, `banners`, `follow_up_count`, `is_suspicious`, `reply_count`, channel.
- **Output:** one closed set of actions — `Reply(context)`, `AskForNumber`, `CancelViewing(reason)`, `Handoff`, `FollowUp(n)`, `Skip(reason)`, `Hold(reason)`.
- **Callers:** `process_account_replies` and the WhatsApp handler both call it; the ~700-line orchestrator collapses to *gather facts → `decide()` → execute*.

### 4.3 Cancellation-as-obligation service (replaces the three copies)

- When a viewing becomes booked and the objective is met (or will be), persist an explicit **`cancellation_due_at`**:
  - datetime known → `viewing_time − random(3.2–4.8h)` (keeps the natural timing);
  - **datetime unknown → due now** (never gamble on a window we can't compute);
  - hard fallback: if a run is about to pass the viewing time uncancelled, due now.
- **One sweeper** discharges everything past due, **independent of** the account's outreach cooldown/bench, the exact stage, and datetime-parse success. Absorbs the WhatsApp `last_stage_change` fallback.
- Both channels call the same service; whichever channel currently holds the conversation sends the cancel.
- **Cancellation message must give a concrete, mundane reason** (product decision 2026-08-13), not today's vague *"something came up."* Draw from a small varied set of believable rental reasons — e.g. *"we've found another place that works for us,"* *"we've decided to renew our current lease,"* *"our move got pushed back."* Requirements: pick **one** reason per thread and keep it consistent; **vary across threads** so it isn't a detectable stock line; stay **non-dramatic** (no emergencies/medical); and when the reason is a clean close (e.g. found another place), **do not offer to reschedule** (contradictory, and it removes the reschedule loop). A concrete reason also makes OpenRent's subsequent *"no longer interested"* notice coherent. **Code note:** `build_cancel_viewing_prompt` (`prompts.py:871`) currently *forbids* reasons and its examples are all vague — it must be rewritten; both channels share `generate_cancellation_message` (`replies.py:453`), so this is a single change.

### 4.4 Datetime extractor fix (feeds 4.3's timing, not its reliability)

- Replace/augment `_try_save_viewing_datetime` so it parses the formats it currently misses (day-of-week + `Xpm`/`X.XXpm`, "today/tomorrow", ranges like "6–6:30pm", "this Thu/Fri evening").
- Reliability of cancellation must **not** depend on this — 4.3 cancels even when the datetime is null. The extractor only sharpens *timing*.

### 4.5 Phone-key identity (cross-channel)

- Add `match_by_phone(incoming_number → Conversation.extracted_phone)` as the **first** WhatsApp matching step, before evidence matching.
- Carry `thread_id` / `listing_id` + captured phone **explicitly at handoff** from OpenRent to WhatsApp, instead of re-deriving via "which property?".
- Resolves ~44% of WhatsApp contacts instantly, removes most property-asks, and unblocks their cancellation obligation.
- **Carry the persona's gender + its specific husband number at handoff** so the cover story stays consistent across channels (fixes P8a). Make the *"my husband/my wife"* framing **gender-aware** rather than hardcoded.
- **Provision distinct numbers** per account (or per small bounded group) and backfill the 15 accounts with none — today all 8 mobile-enabled accounts share `7599390221` (P8b/P8c), which is both a footprint single-point-of-failure and the source of the WhatsApp match ambiguity. Distinct numbers make the phone-key a clean identity key.

### 4.6 Port WhatsApp's guards down to OpenRent

Adopt on the OpenRent reply path: reply cap, business-hours + human-delay pacing, suspicious-message hold, and reactive cancel (landlord raises/ cancels the viewing themselves). WhatsApp is the reference implementation.

---

## 5. State machine specification

| State | Meaning | Terminal | Entry facts |
|---|---|---|---|
| `LEAD` | Contacted, no landlord reply yet | no | thread created |
| `ENGAGING` | Two-way conversation, no phone yet | no | landlord replied, `extracted_phone` null |
| `PHONE_CAPTURED` | Number obtained | no | `extracted_phone` set |
| `CANCEL_DUE` | Number obtained **and** a viewing is booked | no | `PHONE_CAPTURED` + `viewing_confirmed` |
| `HANDED_OFF` | Number obtained, no viewing to cancel | **yes** | `PHONE_CAPTURED`, no booking |
| `CANCELLED` | Cancellation sent | **yes** | `cancellation_sent_at` set |
| `DEAD` | Short-term / duplicate / suspicious / reply-disabled | **yes** | respective signal |

Transition rules: **advance only, never downgrade** (extends the existing `_STAGE_RANK` idea). One writer: `transition(thread, to_state, reason)` with structured logging; illegal transitions rejected.

---

## 6. `decide()` contract → test matrix

Every audited failure becomes a unit test (pure function, no I/O):

| Situation (facts) | Correct action | Guards against |
|---|---|---|
| `has_phone`, no viewing booked | `Handoff` (terminal) | P1 post-capture loop |
| `has_phone`, viewing booked, not yet cancelled | `CancelViewing` | P1 + P2 no-show |
| `has_phone`, viewing booked, no datetime | `CancelViewing` (due now) | P2 + P3 |
| `has_phone`, landlord asks a question | `Skip`/`Handoff` (don't re-engage) | P1 tail spiral |
| `has_phone`, landlord shares number again | `Skip` (already have it) | number re-ask |
| no phone, coordination moment, not yet asked | `AskForNumber` (the tactic) | preserve tactic |
| no phone, landlord refused / "are you a bot" | `Hold`/one alternate, then `Skip` | repetition, bot-tell |
| viewing time passed, uncancelled | `CancelViewing` immediately | P2 late-cancel |
| reschedule being negotiated | do **not** auto-cancel until settled | P4 mid-reschedule |
| short-term / duplicate / suspicious | `Skip`/`DEAD` | misc |
| time-anchored line whose time is now past | suppress (never resend "arriving at 2pm") | stale-message tell |

Plus **characterization tests**: replay a sample of real conversations from the DB through a decider configured to mimic today's behaviour, freezing current output as golden before any change.

---

## 7. Data model changes

- `conversations`: add `lifecycle_state` (canonical enum) and `cancellation_due_at` (timestamp). Keep existing columns; backfill `lifecycle_state` from current facts in a migration.
- `whatsapp_contacts`: no schema change required for phone-key matching (already has `phone_number`, `cancellation_sent_at`).
- Treat `conversation_stage` + the `viewing_*` fields as a **frozen contract** at the channel boundary until WhatsApp is migrated onto the shared service in lockstep (P5).

---

## 8. Rollout plan (how this lands without regressing)

1. **Characterization tests** — replay real conversations; freeze current behaviour as golden.
2. **Build `decide()` pure + fully unit-tested** — every row in §6.
3. **Shadow mode** — run the decider alongside the live loop; **log what it *would* do vs. what the old code did, without acting**, on real traffic for several days. Diff disagreements. **Include the WhatsApp cancellation sweep in the shadow diff** (cross-channel).
4. **Cancellation-as-obligation first** — ship §4.3 as its own slice behind a flag; it is independently the highest-value safety win (no-show/ban risk) and lowest-coupling.
5. **Flagged cutover** — `REPLY_DECIDER_V2`, per-account or percentage; old path retained for instant rollback.
6. **Cleanup** — delete the three divergent cancel copies and the old branching once shadow diffs are clean.

---

## 9. Non-goals / preserved behaviour

- The "on my way / number to coordinate" extraction tactic — **kept**.
- Persona cover stories (e.g. WhatsApp "my wife handles our enquiries") — **kept**.
- Timed, natural-looking cancellation (~3–5h before) when a datetime is known — **kept** (now with a reliable fallback).
- No change to discovery/scraping or initial-outreach content in this doc (tracked separately).

---

## 10. Resolved decisions

1. **Cancel timing → timed + hard fallback.** Keep the natural ~3–5h-before cancel; cancel immediately when there is no datetime or a run would otherwise pass the viewing time (§4.3). Guaranteed, but natural-looking when timing is known.
2. **"No longer interested" footprint → accept it; fix reliability only.** This decision was gated on measuring ban correlation. The analysis (Appendix C) found **no measurable link** between cancellation/withdrawal-notice volume and account bans: account-level auth-failure/captcha signals are ~zero fleet-wide and do not track cancel rate, and cancelled threads are *less* likely to be `REPLY_DISABLED` (4.4% vs 7.6%, confounded by success). The one weak signal — withdrawal-notice threads `REPLY_DISABLED` at 14% vs 6.7% (n=50) — is plausibly just OpenRent closing withdrawn enquiries. **Caveat:** the analysis cannot see *shadow-banning* (declining reply rates), which is the more likely real ban vector and is driven by behavioural tells (no-shows, repetition), **not** the cancel footprint — reinforcing P1/P2 as the priorities. Decision: keep explicit cancels, never fire mid-reschedule; revisit only if a future shadow-ban metric implicates cancellations.
3. **Persona income/job (P7) → tracked separately.** Ship as a small independent `personas.py` fix (bind income band to job title); out of scope for this lifecycle work.
4. **WhatsApp migration → Phase 2.** Freeze `conversation_stage` + `viewing_*` as a contract now; migrate the WhatsApp cancel sweep onto the shared cancellation service **after** the OpenRent slice ships and shadow-diffs are clean.

---

## Appendix A — Key code references (prod)

- `scripts/process_replies.py:658` — terminal-stage skip set (the only stop gate).
- `scripts/process_replies.py:~1023/1113` — phone capture sets `PHONE_ACQUIRED` (status) then `continue`; no stage-terminal.
- `scripts/process_replies.py:~1330` — `generate_reply()` call; no `extracted_phone` guard.
- `scripts/process_viewing_reminders.py:46` — cancellation pre-flight guard (datetime + confirmed + `VIEWING_BOOKED`).
- `app/whatsapp/repository.py:~434` — WhatsApp cancellation selector reading `conversation_stage`.
- `app/whatsapp/matcher.py` — evidence (name/property) matching only; no `match_by_phone`.
- `app/ai/personas.py:298` — `INCOME_BANDS` keyed by persona type; job list at `:227`.
- `app/db/status.py` — the overlapping `status` / `conversation_stage` vocabulary.

## Appendix B — Evidence snapshot (2026-08-13, prod)

- Captured threads non-terminal: **47%** (174/370); of those **146** have no datetime.
- No-show complaints: **70**; never cancelled **51%**; no datetime **27%**; `viewing_confirmed` **97%**.
- Datetime nulls with a parseable time actually present: **88%** (106/120).
- "No longer interested": **48** verbatim / 50 landlords; **86%** post-cancellation.
- WhatsApp: **52** contacts; **35%** matched; **23** numbers already captured on OpenRent; **0** ban/bot/stop signals.
- Post-capture message mix: **~62%** cancellations; genuine gratuitous replies concentrated in a tail.
- Persona gender (P8): **19/23** female (correct); **4/23** male-or-ambiguous primaries — accts 6 (Daniel), 29 (Michael), 10 (Sam), 13 (Alex); acct 13 is live with a number.
- WhatsApp number (P8): **8/23** accounts have a `mobile_number`; **all 8 share `7599390221`**; 15 accounts (incl. 21) have none.

## Appendix C — Ban-correlation analysis (2026-08-13, decision §10.2)

Tested whether cancellations / the "no longer interested" footprint correlate with account or thread shutdown. **No meaningful correlation found.**

- Thread-level `REPLY_DISABLED` risk: **cancellation sent 4.4%** (35/801) vs **no cancellation 7.6%** (173/2265) — cancelled threads are *less* likely to be disabled (they mark successful captures).
- Withdrawal-notice threads: **14.0%** `REPLY_DISABLED` (7/50) vs **6.7%** baseline — the only elevated signal, but n=50 and likely benign (OpenRent closing a withdrawn enquiry).
- Account-level: `session_auth_failures` and `session_captcha_triggers` are ~**0** across the fleet and do not track cancel rate. High- vs low-cancel cohorts: `REPLY_DISABLED` 6.5% vs 5.8%, authFail 0.0 vs 0.5, captcha 0.0 vs 0.0.
- **Limitation:** does not detect shadow-banning (declining reply rates) — the more probable ban vector, driven by behavioural tells (no-shows, repetition), not the cancellation footprint. Reinforces P1/P2 as the ban-risk priorities.
