import re
import time

from openai import APIError, APITimeoutError, OpenAI, RateLimitError

from app.config import settings
from app.ai.prompts import (
    build_phone_extraction_prompt
)
from app.utils.logger import logger


client = OpenAI(
    api_key=settings.OPENAI_API_KEY,
    timeout=25.0
)


# Phone candidates are matched in the RAW text, allowing only the separators
# people actually type inside a number (space, dot, hyphen). Stripping every
# non-digit first (the old approach) fused unrelated numbers into phantom
# leads: "available 07/10, rent 1450, deposit 1673" -> "07101450167".
_PHONE_SEP = r"[ \t.\-]{0,2}"
_PHONE_CANDIDATE_RE = re.compile(
    r"(?<![\d+])(?:"
    # +44 / 0044, optional "(0)" or stray 0, then a 10-digit national number.
    rf"(?:\+|00){_PHONE_SEP}44{_PHONE_SEP}(?:\(0\){_PHONE_SEP}|0{_PHONE_SEP})?[1-9](?:{_PHONE_SEP}\d){{9}}"
    # bare 447… mobile written without the plus
    rf"|44{_PHONE_SEP}7(?:{_PHONE_SEP}\d){{9}}"
    # national 07… mobile
    rf"|0{_PHONE_SEP}7(?:{_PHONE_SEP}\d){{9}}"
    # …typed with a letter o for the zero ("o7484318755", thread 47011441: the
    # landlord's number sat in the chat and we cancelled the viewing anyway)
    rf"|(?<![A-Za-z])[oO]{_PHONE_SEP}7(?:{_PHONE_SEP}\d){{9}}"
    r")(?!\d)"
)
# Digit fragment at the end / start of a message, for numbers split across
# consecutive messages ("call 07958" + "354059. Cheers").
_TAIL_FRAGMENT_RE = re.compile(r"(?:\+|00)?[\d \t.\-()]*\d[ \t]*$")
_HEAD_FRAGMENT_RE = re.compile(r"^[ \t]*[\d \t.\-]*\d")
_PURE_FRAGMENT_RE = re.compile(r"^[ \t]*(?:\+|00)?[\d \t.\-()]*\d[ \t]*$")


def _canonical_phone(raw):
    """Digits-only form of a matched candidate, keeping the +44 prefix:
    "+44 (0)7700 900123" -> "+447700900123", "0044 7911…" -> "+447911…",
    "07911 123 456" -> "07911123456", "447911123456" stays as is."""
    intl = raw.lstrip().startswith(("+", "00"))
    raw = re.sub(r"^(\s*)[oO]", r"\g<1>0", raw)  # "o7…" -> "07…"
    digits = re.sub(r"\D", "", raw)
    if intl:
        if digits.startswith("0044"):
            digits = digits[2:]
        national = digits[2:]
        if national.startswith("0"):
            national = national[1:]
        return "+44" + national
    return digits


def _candidates(text):
    return [_canonical_phone(m.group(0)) for m in _PHONE_CANDIDATE_RE.finditer(text or "")]


def regex_extract_phone(messages):
    """Return the most-recent valid UK phone number found in `messages`.

    Processes messages individually in order so a landlord correction (later
    message) overwrites an earlier, incorrect number.
    """
    msgs = [m or "" for m in (messages or [])]

    # Pass 1: per-message. A later message's number wins (landlord correction);
    # within one message the first number is taken.
    last_found = None
    for msg in msgs:
        found = _candidates(msg)
        if found:
            last_found = found[0]
    if last_found:
        return last_found

    # Pass 2: a number split across consecutive messages ("077144" then
    # "36232"). Only the trailing digit fragment of one message is joined to the
    # leading fragment of the next (a middle message may be a pure fragment),
    # and the match must cross the join, so unrelated numbers elsewhere in the
    # messages ("6:30pm", "32 sqm") can never be fused into a phantom number.
    for i in range(len(msgs) - 1):
        tail = _TAIL_FRAGMENT_RE.search(msgs[i])
        if not tail:
            continue
        combined = tail.group(0).strip()
        for j in range(i + 1, min(i + 3, len(msgs))):
            join_at = len(combined)
            head = _HEAD_FRAGMENT_RE.search(msgs[j])
            if not head:
                break
            combined += head.group(0).strip()
            for m in _PHONE_CANDIDATE_RE.finditer(combined):
                if m.start() < join_at < m.end():
                    return _canonical_phone(m.group(0))
            # Only keep stitching through a message that is itself just digits.
            if not _PURE_FRAGMENT_RE.match(msgs[j]):
                break
    return None


def ai_extract_phone(messages, retries=3, base_delay=2):

    text = "\n".join(messages)

    prompt = build_phone_extraction_prompt(
        text
    )

    for attempt in range(1, retries + 1):

        try:

            response = client.chat.completions.create(
                model=settings.OPENAI_UTILITY_MODEL,

                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],

                temperature=0
            )

            result = (
                response.choices[0]
                .message.content
                .strip()
            )

            if result.upper() == "NONE":
                return None

            return result

        except (RateLimitError, APITimeoutError, APIError) as e:
            logger.warning(
                f"OpenAI phone extraction attempt {attempt}/{retries} failed: {e}"
            )

            if attempt < retries:
                time.sleep(base_delay * attempt)

        except Exception as e:
            logger.exception(f"Unexpected AI phone extraction error: {e}")
            break

    return None
