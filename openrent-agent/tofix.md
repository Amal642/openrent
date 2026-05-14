# To Fix — Audit Issues

## Critical

### 1. `generate_reply()` tuple never unpacked
**File:** `scripts/process_replies.py:241-244`

`generate_reply()` always returns a `(reply, error)` tuple. The caller treats it as a plain string:

```python
reply = generate_reply(messages)
if not reply:   # tuple is always truthy — never fires
```

When it "works", `reply` is `("Hi there...", None)` — that tuple representation gets saved to the DB and typed literally into the message box.

**Fix:** Unpack the return value:
```python
reply, error = generate_reply(messages)
if not reply:
    # handle error
```

---

### 2. AI reply never actually sent
**File:** `app/openrent/inbox.py:321-324`

Submit button click is commented out and never re-enabled:

```python
# TEST MODE
# await submit_button.click()
print("AI reply ready")
return True
```

Every `AI_REPLIED` status in the DB is a lie — the system types the reply but never submits it.

**Fix:** Uncomment `await submit_button.click()` and remove the TEST MODE comment.

---

### 3. Duplicate column drops `unique=True` constraint
**File:** `app/db/models.py:130` and `145-148`

`extracted_phone` is defined twice on the `Conversation` model. The second definition overwrites the first, silently dropping `unique=True`:

```python
extracted_phone = Column(String, unique=True, nullable=True)  # line 130 — overwritten
...
extracted_phone = Column(String, nullable=True)               # line 145 — wins
```

No DB-level uniqueness is enforced. The app-level `phone_exists()` check is the only guard, and it's a race condition under concurrent workers.

**Fix:** Remove the second definition (lines 145-148). Keep the one on line 130 with `unique=True`.

---

### 4. `Landlord` model not imported in repository.py (dormant)
**File:** `app/db/repository.py:1-9`

`get_or_create_landlord()` and `update_landlord_scan()` reference the `Landlord` model but it is not in the import block. Currently safe because the call sites in `process_replies.py` are commented out — enabling agent-filtering logic would immediately crash with `NameError`.

**Fix:** Add `Landlord` to the import:
```python
from app.db.models import (
    Account,
    SearchProfile,
    Listing,
    Conversation,
    Message,
    Landlord  # add this
)
```

---

## High

### 5. All repository functions leak DB sessions on exception
**File:** `app/db/repository.py` — every function

No `try/finally` anywhere. Pattern throughout:
```python
db = SessionLocal()
# ... operations that can throw ...
db.close()  # never reached if exception occurs
```

Under production load, exceptions will exhaust the connection pool and hang the app.

**Fix:** Wrap every function body with `try/finally`, or use a context manager:
```python
db = SessionLocal()
try:
    # ... operations ...
    db.commit()
    return result
finally:
    db.close()
```

---

### 6. Phone regex misses spaced UK numbers — most phones are skipped
**File:** `app/ai/extractors.py:15-35`

Pattern `07\d{9}` requires 9 digits immediately after `07`. Real messages contain `07777 123 456` or `07777-123-456`. The function doesn't strip non-digit characters before matching, so the majority of valid UK numbers fail regex and fall through to the slower, costlier AI extraction.

Compare to the unused implementation in `app/openrent/inbox.py:218-220` which correctly does:
```python
cleaned = re.sub(r"[^\d+]", "", combined_text)
```

**Fix:** Pre-clean the text in `regex_extract_phone()`:
```python
def regex_extract_phone(messages):
    combined = "\n".join(messages)
    cleaned = re.sub(r"[^\d+]", "", combined)  # strip spaces/dashes
    patterns = [...]
    for pattern in patterns:
        match = re.search(pattern, cleaned)
        ...
```

---

### 7. `ai_extract_phone()` has no error handling
**File:** `app/ai/extractors.py:38-68`

The OpenAI call has no try/except, no retry, no timeout. Any API error (rate limit, timeout, network blip) raises an unhandled exception. The outer try/except in `process_replies.py:299` catches it but marks the thread `AI_FAILED` with no context — indistinguishable from a logic failure.

Compare to `generate_reply()` which has proper 3-attempt retry with exponential backoff.

**Fix:** Add retry logic or at minimum a try/except that returns `None` on API errors, same pattern as `generate_reply()`.

---

## Medium

### 8. Inbox page 0 fetched twice on every run
**File:** `app/openrent/inbox.py:117-127`

Page 0 is loaded before the loop to get the total page count, then loaded again on the first loop iteration (`page_num=0`, `start=0`):

```python
await open_inbox_page(page, start=0)       # fetch page 0
total_pages = await get_total_pages(page)
for page_num in range(total_pages):
    start = page_num * 10
    await open_inbox_page(page, start=start)  # fetches page 0 again first
    threads = await extract_reply_threads(page)
```

**Fix:** Extract threads from the already-loaded first page before entering the loop, then loop from page 1 onwards.

---

## Low

### 9. Duplicate import of `send_reply`
**File:** `scripts/process_replies.py:4-25`

`send_reply` is imported from `app.openrent.inbox` twice — once in the first import block and again on line 23.

**Fix:** Remove the duplicate import.

---

### 10. Unreachable dead code — duplicate submit button check
**File:** `app/openrent/messaging.py:104-108`

```python
if not submit_button:
    raise Exception("Correct submit button not found")

if not submit_button:   # identical check, unreachable
    raise Exception("Submit button not found")
```

**Fix:** Delete lines 107-108.

---

### 11. Two phone extraction implementations — one unused, one buggy
**Files:** `app/openrent/inbox.py:211-238` and `app/ai/extractors.py:15-35`

Two separate `extract_phone_number` functions exist. The one in `inbox.py` pre-strips non-digit characters (correct). The one in `extractors.py` doesn't (buggy — see issue #6). The correct `inbox.py` version is never called anywhere.

**Fix:** Delete the function in `inbox.py:211-238` after fixing `extractors.py` (issue #6). One implementation, done correctly.
