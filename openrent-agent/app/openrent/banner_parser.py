"""
Deterministic viewing-state extraction from OpenRent system banners.

OpenRent injects two authoritative status banners into thread HTML:
  - "Viewing Requested"
  - "Viewing confirmed for <weekday> <day> <month> [<year>] at <HH:MM> [AM|PM]"

These are the primary source of truth for viewing state — they require no
AI interpretation and are unambiguous.
"""
import re
from datetime import datetime

from app.utils.logger import logger


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}

# Matches e.g. "Viewing confirmed for Sunday 7th June at 1:00 PM"
#                                     ^weekday ^day      ^month ^time  ^suffix
_CONFIRMED_RE = re.compile(
    r"viewing confirmed for\s+"
    r"(?:\w+\s+)?"                       # optional weekday
    r"(\d{1,2})(?:st|nd|rd|th)?\s+"     # day number
    r"(\w+)"                             # month name
    r"(?:\s+(\d{4}))?"                   # optional year
    r"\s+at\s+"
    r"(\d{1,2}):(\d{2})"                 # HH:MM
    r"(?:\s*(am|pm))?",                  # optional am/pm
    re.I,
)


def parse_banner_datetime(text: str, now: datetime | None = None) -> datetime | None:
    """
    Parse the datetime from a 'Viewing confirmed for ...' banner string.
    Returns None if the text does not match or the date values are invalid.
    """
    now = now or datetime.utcnow()
    match = _CONFIRMED_RE.search(text)
    if not match:
        return None

    day = int(match.group(1))
    month_name = match.group(2).lower()
    year_str = match.group(3)
    hour = int(match.group(4))
    minute = int(match.group(5))
    suffix = (match.group(6) or "").lower()

    month = _MONTHS.get(month_name)
    if not month:
        logger.warning(f"parse_banner_datetime: unknown month name '{month_name}' in {text!r}")
        return None

    if year_str:
        year = int(year_str)
    else:
        year = now.year

    if suffix == "pm" and hour < 12:
        hour += 12
    elif suffix == "am" and hour == 12:
        hour = 0

    try:
        return datetime(year, month, day, hour, minute)
    except ValueError as exc:
        logger.warning(f"parse_banner_datetime: invalid date values in {text!r}: {exc}")
        return None


async def extract_thread_banners(page) -> dict:
    """
    Scan the currently-open thread page for OpenRent viewing status banners.

    Returns a dict:
      viewing_requested  – True if "Viewing Requested" banner is present
      viewing_confirmed  – True if "Viewing confirmed for …" banner is present
      viewing_datetime   – datetime parsed from confirmed banner, or None
    """
    result: dict = {
        "viewing_requested": False,
        "viewing_confirmed": False,
        "viewing_datetime": None,
    }

    try:
        banner_texts: list[str] = []

        # System banners are in bordered, centered divs — NOT inside .message-content.
        # Query them directly first using the stable OpenRent class pattern.
        banner_elements = await page.query_selector_all(
            ".align-items-center.border-top.border-bottom"
        )
        for el in banner_elements:
            text = (await el.inner_text()).strip()
            if text and "viewing" in text.lower():
                banner_texts.append(text)

        # Phase 1: check banner divs with strict phrases only — no risk of false
        # positives from landlord message text.
        _banner_confirmed_phrases = (
            "viewing confirmed for",
            "viewing confirmed",
            "viewing booked",
            "viewing arranged",
        )
        for text in banner_texts:
            tl = text.lower()
            if "viewing requested" in tl and not result["viewing_requested"]:
                result["viewing_requested"] = True
                logger.info(f"VIEWING_REQUESTED_DETECTED banner={text!r}")
            if any(p in tl for p in _banner_confirmed_phrases) and not result["viewing_confirmed"]:
                result["viewing_confirmed"] = True
                dt = parse_banner_datetime(text)
                result["viewing_datetime"] = dt
                if dt:
                    logger.info(
                        f"VIEWING_CONFIRMED_BANNER_DETECTED "
                        f"banner={text!r} datetime={dt}"
                    )
                    logger.info(f"VIEWING_DATETIME_EXTRACTED datetime={dt}")
                else:
                    logger.warning(
                        f"VIEWING_CONFIRMED_BANNER_DETECTED datetime_parse_failed "
                        f"banner={text!r} viewing_confirmed=True viewing_datetime=None"
                    )

        # Phase 2: if no banner divs matched, fall back to a full body scan so
        # structural HTML changes don't silently break detection.
        if not result["viewing_confirmed"] and not result["viewing_requested"]:
            full_text: str = await page.evaluate("document.body.innerText")
            for line in full_text.splitlines():
                line = line.strip()
                if not line or "viewing" not in line.lower() or len(line) >= 300:
                    continue
                tl = line.lower()
                if "viewing requested" in tl and not result["viewing_requested"]:
                    result["viewing_requested"] = True
                    logger.info(f"VIEWING_REQUESTED_DETECTED fallback_body banner={line!r}")
                # Use only strict phrases in the body scan — "viewing for" is too broad
                # and would false-positive on landlord messages like "arrange a viewing for..."
                if any(p in tl for p in _banner_confirmed_phrases) and not result["viewing_confirmed"]:
                    result["viewing_confirmed"] = True
                    dt = parse_banner_datetime(line)
                    result["viewing_datetime"] = dt
                    if dt:
                        logger.info(
                            f"VIEWING_CONFIRMED_BANNER_DETECTED fallback_body "
                            f"banner={line!r} datetime={dt}"
                        )
                        logger.info(f"VIEWING_DATETIME_EXTRACTED datetime={dt}")
                    else:
                        logger.warning(
                            f"VIEWING_CONFIRMED_BANNER_DETECTED fallback_body datetime_parse_failed "
                            f"banner={line!r} viewing_confirmed=True viewing_datetime=None"
                        )

    except Exception as exc:
        logger.warning(f"extract_thread_banners failed: {exc}")

    return result
