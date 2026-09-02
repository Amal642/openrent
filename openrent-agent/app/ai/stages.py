import re
from datetime import datetime, timedelta, timezone

from app.db.status import (
    VIEWING_DISCUSSION,
    VIEWING_BOOKED,
    VIEWING_PENDING,
)


def _stage_log(event: str, detail: str = "") -> None:
    msg = f"STAGE_EVENT {event}"
    if detail:
        msg += f" | {detail}"
    print(msg)


BOOKED_PATTERNS = [
    r"\bsee you\b",
    r"\bconfirmed\b",
    r"\bbooked\b",
    r"\bappointment\b",
    r"\bcome at\b",
    r"\bmeet at\b",
    r"\bmeet you\b",
    r"\bsee you then\b",
    r"\bsee you tomorrow\b",
    r"\blooking forward to (meeting|seeing) you\b",
    r"\bsee you there\b",
]

DISCUSSION_PATTERNS = [
    r"\bwhat time\b",
    r"\bavailable\b",
    r"\bviewings?\b",
    r"\bwhen can you\b",
    r"\bwhat day\b",
    r"\brearrange\b",
    r"\breschedule\b",
    r"\banother time\b",
]

NEGATING_PATTERNS = [
    r"\bcancel\b",
    r"\bcan't make\b",
    r"\bcannot make\b",
    r"\bnot available\b",
    r"\bno longer\b",
]

TIME_PATTERN = re.compile(
    r"\b([01]?\d|2[0-3])(?:[:.]([0-5]\d))?\s*(am|pm)?\b",
    re.I,
)
WEEKDAY_PATTERN = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|today)\b",
    re.I,
)
NUMERIC_DATE_PATTERN = re.compile(
    r"\b([0-3]?\d)[/-]([01]?\d)(?:[/-](\d{2,4}))?\b"
)
# Default hour for a viewing given only a part-of-day (no clock time), e.g.
# "Thursday evening" — used so such viewings still get a timed datetime (P3).
PART_OF_DAY_HOURS = {"morning": 10, "afternoon": 14, "evening": 18, "night": 19}


def _message_text(message):
    return str(message.get("message") or message.get("content") or "")


def _recent_messages(messages, limit=8):
    return list(messages or [])[-limit:]


def _matches_any(text, patterns):
    return any(re.search(pattern, text, re.I) for pattern in patterns)


def _date_spans(text):
    return [match.span() for match in NUMERIC_DATE_PATTERN.finditer(text)]


def _overlaps_any(span, spans):
    start, end = span
    return any(start < other_end and end > other_start for other_start, other_end in spans)


def _is_explicit_time_match(match) -> bool:
    """Return False for bare integers (e.g. '1' in '1 bed flat', '4' in '4 months').
    A real time reference requires either HH:MM format or an am/pm suffix."""
    has_minutes = match.group(2) is not None
    has_ampm = bool((match.group(3) or "").strip())
    return has_minutes or has_ampm


def _message_time(message):
    """Best-effort naive-UTC datetime for WHEN a message was sent.

    Relative/underspecified dates ("6:15pm", "Tuesday") must resolve against the
    moment the landlord spoke, not when the worker happens to process the thread
    (a processing lag pushed one real viewing 2 days into the future). Returns
    None when no timestamp is present, so callers fall back to `now`.
    """
    if not isinstance(message, dict):
        return None
    for key in ("timestamp", "received_at", "created_at"):
        value = message.get(key)
        if value in (None, ""):
            continue
        dt = value if isinstance(value, datetime) else _parse_message_ts(str(value))
        if dt is not None:
            if dt.tzinfo is not None:
                dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
            return dt
    return None


def _parse_message_ts(value):
    value = value.strip()
    if not value:
        return None
    try:
        if value.isdigit():
            numeric = int(value)
            if numeric > 10_000_000_000:  # milliseconds
                numeric = numeric / 1000
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
    except Exception:
        pass
    for candidate in (value, value.replace("Z", "+00:00")):
        try:
            return datetime.fromisoformat(candidate)
        except Exception:
            pass
    return None


def _target_date_from_text(text, now):
    if "day after tomorrow" in text:
        return (now + timedelta(days=2)).date()
    if "tomorrow" in text:
        return (now + timedelta(days=1)).date()
    if "today" in text:
        return now.date()

    for match in NUMERIC_DATE_PATTERN.finditer(text):
        day = int(match.group(1))
        month = int(match.group(2))
        year_text = match.group(3)
        year = now.year
        if year_text:
            year = int(year_text)
            if year < 100:
                year += 2000
        try:
            candidate = datetime(year, month, day).date()
        except ValueError:
            continue
        if candidate < now.date() and not year_text:
            try:
                candidate = datetime(year + 1, month, day).date()
            except ValueError:
                continue
        return candidate

    weekdays = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }
    for name, index in weekdays.items():
        if name in text:
            days_ahead = (index - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (now + timedelta(days=days_ahead)).date()

    return now.date()


# Month names (full + common abbreviations) for "3rd September" / "Sept 3" style
# dates, which _target_date_from_text (numeric dd/mm + weekday only) cannot read.
_MONTH_NAMES = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7,
    "aug": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
# Longest names first so "september" wins over "sep" in the alternation.
_MONTH_ALT = "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))
_DAY_MONTH_RE = re.compile(  # "3rd September", "3 Sept"
    rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\b", re.I
)
_MONTH_DAY_RE = re.compile(  # "September 3rd", "Sept 3"
    rf"\b({_MONTH_ALT})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", re.I
)

_WEEKDAY_INDEX = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}


def _resolve_day_month(text, ref):
    """Resolve an ordinal-day + month-name date ('3rd September') to a date, or
    None. Rolls to next year only when the date is clearly in the past."""
    for rex, day_grp, mon_grp in ((_DAY_MONTH_RE, 1, 2), (_MONTH_DAY_RE, 2, 1)):
        match = rex.search(text)
        if not match:
            continue
        day = int(match.group(day_grp))
        month = _MONTH_NAMES.get(match.group(mon_grp).lower())
        if not month:
            continue
        try:
            candidate = datetime(ref.year, month, day).date()
        except ValueError:
            continue
        if candidate < ref.date() - timedelta(days=2):
            try:
                candidate = datetime(ref.year + 1, month, day).date()
            except ValueError:
                continue
        return candidate
    return None


def _explicit_target_date(text, ref):
    """The explicit calendar day named in THIS text, or None.

    Unlike _target_date_from_text this NEVER falls back to ref.date(): a None
    return means 'no explicit day stated here', which lets callers tell a real,
    evidence-based day (grounded) apart from a guess. Handles relative words,
    ordinal+month names, numeric dd/mm dates, and a SINGLE unambiguous weekday
    (two weekdays like 'Friday or Saturday' are ambiguous -> None, deferred to
    the LLM)."""
    if "day after tomorrow" in text:
        return (ref + timedelta(days=2)).date()
    if "tomorrow" in text:
        return (ref + timedelta(days=1)).date()
    if "today" in text:
        return ref.date()

    day_month = _resolve_day_month(text, ref)
    if day_month is not None:
        return day_month

    for match in NUMERIC_DATE_PATTERN.finditer(text):
        day = int(match.group(1))
        month = int(match.group(2))
        year_text = match.group(3)
        year = ref.year
        if year_text:
            year = int(year_text)
            if year < 100:
                year += 2000
        try:
            candidate = datetime(year, month, day).date()
        except ValueError:
            continue
        if candidate < ref.date() and not year_text:
            try:
                candidate = datetime(year + 1, month, day).date()
            except ValueError:
                continue
        return candidate

    named = {idx for name, idx in _WEEKDAY_INDEX.items()
             if re.search(rf"\b{name}\b", text)}
    if len(named) == 1:
        idx = next(iter(named))
        days_ahead = (idx - ref.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return (ref + timedelta(days=days_ahead)).date()

    return None


def _carry_explicit_day(recent, chosen_idx, fallback_ref):
    """The most recent explicit day stated at/before the chosen message, or None.

    Lets a bare-time confirming line ('8:30 would be fine') inherit the day
    pinned earlier in the thread ('...come on the 3rd September'). Each message's
    own send time anchors its relative words; missing timestamps use fallback_ref.
    """
    for i in range(chosen_idx, -1, -1):
        message = recent[i]
        text = _message_text(message).lower()
        ref = _message_time(message) or fallback_ref
        day = _explicit_target_date(text, ref)
        if day is not None:
            return day
    return None


def _has_time(text):
    date_spans = _date_spans(text)
    return any(
        not _overlaps_any(match.span(), date_spans) and _is_explicit_time_match(match)
        for match in TIME_PATTERN.finditer(text)
    )


def _has_time_or_day(text):
    """True when text contains a numeric time OR a named weekday/day word.
    Used so 'See you Thursday' qualifies as VIEWING_BOOKED even without a
    specific clock time."""
    return _has_time(text) or bool(WEEKDAY_PATTERN.search(text))


def detect_stage(messages):
    recent = _recent_messages(messages, limit=8)
    if not recent:
        return None

    recent_text = "\n".join(_message_text(m).lower() for m in recent)
    latest_text = _message_text(recent[-1]).lower()

    if _matches_any(latest_text, NEGATING_PATTERNS):
        return VIEWING_DISCUSSION
    if _matches_any(
        latest_text,
        [
            r"\brearrange\b",
            r"\breschedule\b",
            r"\banother time\b",
            r"\binstead\b",
            r"\bneed to change\b",
            r"\bchange it\b",
        ],
    ):
        return VIEWING_DISCUSSION

    discussion_after_booking = False
    for message in recent[-4:]:
        text = _message_text(message).lower()
        if _matches_any(text, DISCUSSION_PATTERNS) and _matches_any(text, NEGATING_PATTERNS + [r"\bor\b", r"\binstead\b"]):
            discussion_after_booking = True
            break

    if discussion_after_booking:
        return VIEWING_DISCUSSION

    # VIEWING_BOOKED requires a booking phrase AND a specific time/day in the SAME
    # message. Combining signals across different messages causes false positives
    # (e.g. "that works" in one reply + "1 bed flat" in the opener).
    for message in recent:
        text = _message_text(message).lower()
        if _matches_any(text, BOOKED_PATTERNS) and _has_time_or_day(text):
            _stage_log("VIEWING_CONFIRMATION_DETECTED", "booked pattern + time/day in same message")
            return VIEWING_BOOKED

    # Booked-pattern found but no confirmed time — treat as pending, not booked
    if any(_matches_any(_message_text(m).lower(), BOOKED_PATTERNS) for m in recent):
        _stage_log("VIEWING_PENDING", "booked pattern found but no specific time agreed")
        return VIEWING_PENDING

    if _matches_any(recent_text, DISCUSSION_PATTERNS):
        _stage_log("VIEWING_PENDING", "viewing discussion detected, no confirmed time")
        return VIEWING_DISCUSSION

    return None


def _part_of_day_datetime(messages, now):
    """Fallback datetime for "Thursday evening"-style times with no clock time.

    Requires a day anchor (weekday/today/tomorrow) plus a part-of-day word, and
    maps the part-of-day to a default hour. Returns None if either is missing.
    """
    for message in reversed(list(messages or [])):
        text = _message_text(message).lower()
        if not WEEKDAY_PATTERN.search(text):
            continue
        ref = _message_time(message) or now
        for word, hour in PART_OF_DAY_HOURS.items():
            if word in text:
                target_date = _target_date_from_text(text, ref)
                candidate = datetime.combine(
                    target_date, datetime.min.time()
                ).replace(hour=hour)
                if candidate < ref:
                    candidate += timedelta(days=1)
                return candidate
    return None


def _extract_viewing_datetime_impl(messages, now=None):
    """Deterministic viewing-datetime extraction returning ``(datetime, grounded)``.

    ``grounded`` is True when the DAY came from real evidence — an explicit day in
    the chosen message, a day carried from an earlier turn, or a part-of-day
    reference — and False when it fell back to the message date because no day was
    stated. Callers use it to decide whether to trust the deterministic day over
    the LLM's (see resolve_viewing_datetime): a grounded day beats the LLM's
    arithmetic (thread 45969788), but a guessed day yields to the LLM's reading of
    which day was actually agreed (thread 46215267)."""
    now = now or datetime.utcnow()
    recent = _recent_messages(messages, limit=8)

    candidates = []
    for idx, message in enumerate(recent):
        text = _message_text(message).lower()
        # Consider a message with an explicit time that is either about a viewing
        # OR references a specific day (today/tomorrow/weekday). The day clause
        # catches "6-6:30pm today" / "3pm I am here" that state a scheduled time
        # without a viewing keyword (P3), while still ignoring bare numbers like
        # "contact you in 1 day" (which carry no explicit time — see below).
        if not (
            TIME_PATTERN.search(text)
            and (
                _matches_any(text, BOOKED_PATTERNS + DISCUSSION_PATTERNS)
                or WEEKDAY_PATTERN.search(text)
            )
        ):
            continue
        # Anchor date resolution to WHEN this message was sent, not to the
        # worker's processing time. Falls back to `now` if the message carries
        # no timestamp (preserves prior behaviour and the explicit-now tests).
        ref = _message_time(message) or now
        for match in TIME_PATTERN.finditer(text):
            # Require an explicit time (:MM / .MM or am/pm). That alone excludes
            # bare date components like "05"/"06" in "05/06", so no date-overlap
            # check is needed — and dropping it lets "6-6:30pm" keep the 6:30pm
            # time that a greedy "6-6" numeric-date match would otherwise swallow.
            if not _is_explicit_time_match(match):
                continue
            candidates.append((text, match, ref, idx))

    if not candidates:
        fallback = _part_of_day_datetime(recent, now)
        if fallback is not None:
            _stage_log("VIEWING_DATETIME_EXTRACTED", f"part-of-day default datetime={fallback}")
            return fallback, True
        _stage_log("VIEWING_DATETIME_EXTRACTED", "no candidates — no time found in booking/discussion messages")
        return None, False

    combined, time_match, ref, chosen_idx = candidates[-1]

    if not time_match:
        return None, False

    hour = int(time_match.group(1))
    minute = int(time_match.group(2) or 0)
    suffix = (time_match.group(3) or "").lower()

    if suffix == "pm" and hour < 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0
    elif not suffix and 1 <= hour <= 7:
        hour += 12

    # Resolve the DAY. Prefer an explicit day in the chosen message; otherwise
    # carry the most recent explicit day stated earlier in the thread (so a
    # bare-time confirming line inherits "...the 3rd September" from a prior
    # turn); only if neither exists fall back to the message date (ungrounded).
    target_date = _explicit_target_date(combined, ref)
    grounded = target_date is not None
    if target_date is None:
        carried = _carry_explicit_day(recent, chosen_idx, ref)
        if carried is not None:
            target_date, grounded = carried, True
        else:
            target_date, grounded = ref.date(), False

    candidate = datetime.combine(target_date, datetime.min.time()).replace(
        hour=hour,
        minute=minute,
    )

    if candidate < ref:
        candidate += timedelta(days=1)

    _stage_log("VIEWING_DATETIME_EXTRACTED", f"extracted datetime={candidate} grounded={grounded}")
    return candidate, grounded


def extract_viewing_datetime(messages, now=None):
    """Backward-compatible wrapper: the resolved datetime only (or None)."""
    return _extract_viewing_datetime_impl(messages, now)[0]


# --- viewing-time helpers shared with the AI detector -----------------------
EN_ROUTE_PATTERNS = [
    r"\brunning\s+(?:late|\d+)",
    r"\bon (?:my|the) way\b",
    r"\bomw\b",
    r"\bnearly there\b",
    r"\balmost there\b",
    r"\bjust arrived\b",
    r"\bi'?m (?:here|outside|downstairs|waiting)\b",
    r"\bat the (?:property|flat|door|building)\b",
    r"\bsee you (?:shortly|soon|in a bit|in \d+)\b",
    r"\b\d+\s*min(?:ute)?s?\s*(?:late|away|out)\b",
    r"\bbe there in\b",
]
_EN_ROUTE_RE = re.compile("|".join(EN_ROUTE_PATTERNS), re.I)


def message_uk_timestamp_str(message):
    """Human-readable UK timestamp ('Thu 21 Aug 08:07') for a message, or None.
    Anchors the detector's relative-date resolution to when each line was sent."""
    from app.utils.scheduling import utc_naive_to_uk_naive
    dt = _message_time(message)  # naive UTC (or None)
    if dt is None:
        return None
    uk = utc_naive_to_uk_naive(dt)
    return uk.strftime("%a %d %b %H:%M")


def landlord_says_en_route(messages):
    """True if the most recent landlord/inbound message signals they are en route
    or the viewing is imminent (so it must be today, not a future day)."""
    for message in reversed(list(messages or [])):
        if not isinstance(message, dict):
            continue
        sender = str(message.get("sender") or message.get("direction") or "").lower()
        if sender in {"us", "user", "tenant", "outbound", "ai", "assistant"}:
            continue
        text = str(message.get("message") or message.get("content") or "")
        return bool(_EN_ROUTE_RE.search(text))
    return False


def reconcile_viewing_datetime(dt_uk, messages, now=None):
    """En-route guard, in naive UK-local time. When the latest landlord message
    signals they are on their way / running late, the viewing is happening TODAY:
    if the resolved date drifted to a later UK day, snap it back to that message's
    UK date, keeping the agreed clock time. No-op otherwise. DST-safe (no cross-
    zone conversions)."""
    from app.utils.scheduling import utc_naive_to_uk_naive
    if dt_uk is None or not landlord_says_en_route(messages):
        return dt_uk
    anchor_dt = None
    for message in reversed(list(messages or [])):
        if not isinstance(message, dict):
            continue
        sender = str(message.get("sender") or message.get("direction") or "").lower()
        if sender in {"us", "user", "tenant", "outbound", "ai", "assistant"}:
            continue
        anchor_dt = _message_time(message)  # naive UTC
        break
    anchor_uk = (
        utc_naive_to_uk_naive(anchor_dt) if anchor_dt
        else (now or utc_naive_to_uk_naive(datetime.utcnow()))
    )
    if dt_uk.date() <= anchor_uk.date():
        return dt_uk
    corrected = dt_uk.replace(
        year=anchor_uk.year, month=anchor_uk.month, day=anchor_uk.day
    )
    _stage_log(
        "VIEWING_DATETIME_RECONCILED",
        f"en_route signal -> snapped {dt_uk} to {corrected}",
    )
    return corrected


def parse_llm_viewing_datetime(dt_str):
    """Parse the LLM's 'YYYY-MM-DD HH:MM' string to a naive UK-local datetime,
    or None. Kept permissive about the separator."""
    if not dt_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(dt_str).strip(), fmt)
        except ValueError:
            continue
    return None


# A viewing resolved outside this window relative to now is almost certainly an
# arithmetic slip (e.g. an LLM landing a weekday in the wrong month). Used only
# to prefer the alternative source / log — never to silently drop.
_MAX_FUTURE_DAYS = 90
_MAX_PAST_HOURS = 48


def _within_bounds(dt_uk, now_uk):
    if dt_uk is None:
        return False
    if dt_uk > now_uk + timedelta(days=_MAX_FUTURE_DAYS):
        return False
    if dt_uk < now_uk - timedelta(hours=_MAX_PAST_HOURS):
        return False
    return True


def resolve_viewing_datetime(messages, llm_detection=None, now=None):
    """Single source of truth for a viewing datetime (naive UK-local, or None).

    Deterministic, message-anchored extraction is authoritative; the LLM's date
    is a gap-filler only. This removes the LLM from date ARITHMETIC — the class
    of error behind the off-by-one-day no-show (thread 45969788).

    Priority:
      1. deterministic extract_viewing_datetime() (anchored to message time)
      2. if deterministic is None -> the LLM's parsed date (bounded)
      3. if both present but on different days -> deterministic wins (logged)
    Then: en-route reconcile + sanity-bound. Caller converts UK->UTC at save.
    """
    from app.utils.scheduling import utc_naive_to_uk_naive
    now_uk = now or utc_naive_to_uk_naive(datetime.utcnow())

    det, det_grounded = _extract_viewing_datetime_impl(messages, now)
    llm = None
    if isinstance(llm_detection, dict):
        llm = parse_llm_viewing_datetime(llm_detection.get("viewing_datetime"))
    elif isinstance(llm_detection, str):
        llm = parse_llm_viewing_datetime(llm_detection)

    if det is not None and llm is not None:
        if det.date() != llm.date():
            if det_grounded:
                # The deterministic day is evidence-based (an explicit day in the
                # confirming message, or one carried from an earlier turn), so
                # trust it over the LLM — whose weakness is date ARITHMETIC.
                # (thread 45969788)
                _stage_log(
                    "VIEWING_DATETIME_DISAGREEMENT",
                    f"deterministic={det} llm={llm} -> deterministic day (grounded)",
                )
                chosen = det
            else:
                # The deterministic day was a GUESS — no day was stated for this
                # time anywhere in the thread — so the LLM's reading of which day
                # was agreed is more reliable. Keep the deterministic clock time
                # (a direct regex of the stated time) on the LLM's day.
                # (thread 46215267: bare-time confirm, day only in an earlier turn)
                _stage_log(
                    "VIEWING_DATETIME_DAY_FROM_LLM",
                    f"deterministic={det} (ungrounded day) llm={llm} "
                    "-> llm day + deterministic time",
                )
                chosen = datetime.combine(llm.date(), det.time())
        elif det.time() != llm.time():
            # Same day, different time: the regex takes the LAST time in a
            # message, which is wrong when several are named ("make it 4:30 ...
            # booked for 4pm"). The LLM reads which slot was actually agreed, so
            # take its time on the anchored day. (thread 45987890)
            _stage_log(
                "VIEWING_DATETIME_TIME_FROM_LLM",
                f"deterministic={det} llm={llm} -> llm time on deterministic day",
            )
            chosen = datetime.combine(det.date(), llm.time())
        else:
            chosen = det
    elif det is not None:
        chosen = det
    elif llm is not None:
        # Gap-fill: deterministic parser found nothing (e.g. bare-hour phrasing).
        # Trust the LLM's date only if it is sanely bounded.
        if _within_bounds(llm, now_uk):
            chosen = llm
        else:
            _stage_log(
                "VIEWING_DATETIME_SUSPICIOUS",
                f"llm-only={llm} out of bounds vs now={now_uk} -> dropping",
            )
            return None
    else:
        return None

    chosen = reconcile_viewing_datetime(chosen, messages, now=now_uk)

    if not _within_bounds(chosen, now_uk):
        # Prefer the other source if it is in bounds; else keep but flag.
        alt = llm if chosen is det else det
        if _within_bounds(alt, now_uk):
            _stage_log(
                "VIEWING_DATETIME_SUSPICIOUS",
                f"chosen={chosen} out of bounds -> using alternative {alt}",
            )
            chosen = reconcile_viewing_datetime(alt, messages, now=now_uk)
        else:
            _stage_log(
                "VIEWING_DATETIME_SUSPICIOUS",
                f"chosen={chosen} out of bounds vs now={now_uk} (no in-bounds alt)",
            )

    return chosen


# --- outbound stale relative-date guard -------------------------------------
_WEEKDAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
]

# Cues that the reply is proposing an ALTERNATIVE / reschedule rather than
# restating the agreed slot -> never rewrite its day words.
_ALT_CUE_RE = re.compile(
    r"\b(also|either|instead|alternatively|otherwise|reschedule|rearrange|"
    r"another\s+(?:day|time)|move\s+it|push\s+it|change\s+it|could\s+we|"
    r"can\s+we|can\s+you\s+do)\b",
    re.I,
)


def _viewing_time_variants(uk_dt):
    """Strings a reply might use to restate the agreed viewing clock time,
    so we only rewrite a day word that is attached to the SAME slot."""
    h24, m = uk_dt.hour, uk_dt.minute
    h12 = h24 % 12 or 12
    ampm = "am" if h24 < 12 else "pm"
    v = set()
    if m == 0:
        v |= {f"{h12}{ampm}", f"{h12} {ampm}", f"{h12}:00{ampm}",
              f"{h12}:00 {ampm}", f"{h12}.00{ampm}"}
    else:
        v |= {f"{h12}:{m:02d}{ampm}", f"{h12}:{m:02d} {ampm}", f"{h12}.{m:02d}{ampm}"}
    v.add(f"{h24:02d}:{m:02d}")
    return v


def _correct_day_term(viewing_date, now_date):
    delta = (viewing_date - now_date).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return _WEEKDAY_NAMES[viewing_date.weekday()]


def correct_stale_viewing_day(reply, viewing_dt_utc, now=None):
    """Deterministically fix a stale future relative day-word ("tomorrow",
    "day after tomorrow") in an outbound reply that restates an agreed viewing
    time but names the wrong day (the "1pm tomorrow said on the viewing day"
    bug, thread 45969788). Returns the corrected reply, or the reply unchanged.

    Conservative gates (all required): a viewing datetime is known and falls
    today or tomorrow; the reply restates that agreed clock time; the reply is
    not offering an alternative/reschedule; and the day-word actually resolves
    to a different day than the viewing.
    """
    from app.utils.scheduling import utc_naive_to_uk_naive
    if not reply or viewing_dt_utc is None:
        return reply
    now_uk = utc_naive_to_uk_naive(now) if now else utc_naive_to_uk_naive(datetime.utcnow())
    viewing_uk = utc_naive_to_uk_naive(viewing_dt_utc)

    day_delta = (viewing_uk.date() - now_uk.date()).days
    if day_delta not in (0, 1):
        return reply  # only guard imminent viewings; far-future is ambiguous

    low = reply.lower()
    if not any(t in low for t in _viewing_time_variants(viewing_uk)):
        return reply  # reply does not restate the agreed slot
    if _ALT_CUE_RE.search(reply):
        return reply  # offering an alternative / reschedule

    correct_term = _correct_day_term(viewing_uk.date(), now_uk.date())
    result = reply
    for word, offset in (("day after tomorrow", 2), ("tomorrow", 1)):
        if now_uk.date() + timedelta(days=offset) == viewing_uk.date():
            continue  # this word is actually correct for the viewing day
        pat = re.compile(r"\b" + re.escape(word) + r"\b", re.I)
        if pat.search(result):
            result = pat.sub(correct_term, result)
            _stage_log(
                "VIEWING_REPLY_DAY_CORRECTED",
                f"'{word}' -> '{correct_term}' (viewing {viewing_uk.date()}, now {now_uk.date()})",
            )
            break
    return result
