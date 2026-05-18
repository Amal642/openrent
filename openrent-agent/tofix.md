# To Fix - Current Audit Issues

## Critical

### 1. Standalone viewing-cancellation worker can crash at runtime
**File:** `scripts/process_viewing_reminders.py`

The module calls:

```python
if __name__ == "__main__":
    asyncio.run(process_viewing_reminders())
```

before importing `asyncio`, `login`, and `launch_browser`.

`process_viewing_reminders()` uses `launch_browser()` and `login()`, so running this file directly can fail with `NameError` depending on execution order.

**Fix:**
- Move all imports to the top of the file.
- Keep the `if __name__ == "__main__":` block at the very end after imports and function definitions.

---

### 2. Failed reply sends are still recorded as successful
**File:** `scripts/process_replies.py`

The code does:

```python
await send_reply(page, reply)
save_message(thread_id, "outbound", reply)
update_conversation_status(thread_id, AI_REPLIED)
```

But `send_reply()` returns `False` when the textarea or send button is disabled. That return value is ignored. If sending fails, the DB still records the message as sent and marks the thread `AI_REPLIED`.

**Fix:**
- Capture the return value from `send_reply()`.
- Only call `save_message()`, `save_ai_reply()`, `mark_phone_requested()`, and `update_conversation_status(..., AI_REPLIED)` if the send actually succeeds.
- Record a failure status when the UI send fails.

---

### 3. Reply strategy still asks for phone too early
**Files:** `app/ai/prompts.py`

The SOP says:
- book the viewing first
- ask for phone only after the viewing is booked

Current prompts still violate that:
- `build_initial_enquiry_prompt()` includes phone-number-asking language, meaning the model may ask for it during the initial enquiry before any viewing is booked.
- `build_reply_prompt()` for non-booked stages says to "Arrange a viewing and ask for phone number naturally".

This means the stage-aware behavior is only partially implemented.

**Fix:**
- Remove phone-number requests from the initial enquiry prompt.
- Remove phone-number requests from non-booked reply stages.
- Keep phone asking only in the `VIEWING_BOOKED` path.

---

### 4. Stage detection and viewing-time extraction are too unreliable for automation
**File:** `app/ai/stages.py`

Problems:
- `detect_stage()` scans the entire conversation history, so one old "confirmed" or "see you" can keep a thread in `VIEWING_BOOKED` forever.
- `extract_viewing_datetime()` grabs the first time-like token anywhere in the thread, not necessarily the booked appointment.

This can produce:
- wrong `conversation_stage`
- wrong `viewing_datetime`
- mistimed phone requests
- mistimed cancellations

**Fix:**
- Base stage detection on recent landlord/user turns, not the whole thread blindly.
- Extract viewing time from the specific booking exchange, not the first regex hit in the full conversation.
- Add tests covering re-scheduling, old booked messages, and multiple times in one thread.

---

## High

### 5. Bedroom detection is semantically wrong on many listings
**File:** `app/openrent/messaging.py`

`extract_listing_metadata()` currently prefers:

```python
r"Max Tenants:</span>\s*(\d+)"
```

and uses that as `bedrooms`.

`Max Tenants` is not the same as bedroom count. That will feed the wrong value into `generate_household()` and produce the wrong persona/household wording.

**Fix:**
- Parse actual bedroom count first.
- Treat max tenants as a separate field if needed, not as `bedrooms`.

---

### 6. Two Type 2 form mappings are still unverified and may be wrong
**File:** `app/openrent/messaging.py`

Unresolved mappings:
- `ScreeningInfo.HasRightToRent = true` is being used for the SOP item "tenancy >= 6 months", but that field name sounds like immigration status, not tenancy duration.
- Furnishing uses `value="2"` with no proof that it means "I don't mind".

These are not patched; they are only hardcoded guesses.

**Fix:**
- Verify the actual OpenRent field names/options against the live form or a captured DOM snapshot.
- Replace magic values with selectors based on actual labels if possible.
- Document the confirmed mapping in code comments.

---

### 7. Daily phone-target tracking can undercount real leads
**File:** `app/db/repository.py`

`count_phones_today()` filters by:

```python
Conversation.last_message_at >= start
```

But `save_phone_number()` does not update `last_message_at`. If a phone is extracted today from an older thread, it may not count toward today's target.

**Fix:**
- Track phone acquisition time explicitly, e.g. `phone_found_at`.
- Or update a dedicated timestamp when `save_phone_number()` runs.
- Count daily leads using that timestamp instead of `last_message_at`.

---

### 8. Agent-detection failure defaults to contacting the landlord
**File:** `app/openrent/landlords.py`

If landlord ID extraction fails, `landlord_is_agent()` returns `False`, which means "not an agent". Operationally that is unsafe: scraping failure becomes permission to contact.

**Fix:**
- Return a tri-state result (`agent`, `not_agent`, `unknown`) or raise a handled exception.
- Decide explicitly whether `unknown` should skip or retry rather than silently proceed.

---

## Medium

### 9. `send_initial_message()` is brittle around textarea/button selection
**File:** `app/openrent/messaging.py`

Problems:
- It grabs the first `textarea` on the page.
- It only submits buttons containing `"request viewing"`.
- The fallback textarea lookup repeats the same selector and adds no resilience.

This is fragile if OpenRent changes markup or if there are multiple textareas/buttons.

**Fix:**
- Use more specific selectors for the message box.
- Broaden submit detection to support alternate button text if OpenRent changes wording.
- Remove duplicate fallback code and replace it with meaningful locator logic.

---

### 10. Skipped listings are marked as processing failures
**Files:** `scripts/process_listings.py`, `app/db/repository.py`

Agent skips and generic skips currently set `processing_failed = True`.

That mixes business-rule skips with actual failures, which pollutes reporting and makes retry logic harder to reason about.

**Fix:**
- Separate skip state from failure state.
- Use `skip_reason` plus a non-failure terminal state for agents/non-contactable cases as appropriate.

---

### 11. Test coverage is effectively absent for the audited paths
**Files:** `tests/*`, `scripts/test_*.py`

Current state:
- several test files are empty
- `pytest -q` fails during collection because `scripts/test_inbox.py` and `scripts/test_search.py` cannot import `app`

That means there is no reliable regression suite for the messaging, stage, and reminder logic.

**Fix:**
- Fix test import/package configuration so `pytest` can run.
- Add focused tests for:
  - stage detection
  - viewing datetime extraction
  - prompt stage behavior
  - phone lead counting
  - send-failure handling

---

## Low

### 12. `process_replies.py` has stale imports and commented-out dead paths
**File:** `scripts/process_replies.py`

The file imports items that are currently unused and contains a block of commented-out landlord/agent logic. It makes the control flow harder to review and hides what is actually live.

**Fix:**
- Remove unused imports.
- Delete dead commented-out code or move it into a tracked backlog item if it is still planned.

---

### 13. Logging severity is inconsistent in a few places
**File:** `scripts/process_listings.py`

Example:

```python
logger.exception(f"Daily limit reached for account {account.id}")
```

That is not an exception condition; it is normal flow. Using `logger.exception()` produces misleading stack traces/noise.

**Fix:**
- Replace normal-flow `logger.exception()` calls with `logger.info()` or `logger.warning()` as appropriate.

