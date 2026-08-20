import re


PHONE_LIKE_PATTERN = re.compile(
    r"(?<!\w)(?:\+44[\d\s().-]{7,}\d|44[\d\s().-]{8,}\d|0[1-9]\d[\d\s().-]{6,}\d)(?!\w)"
)

# Detect AI-generated template placeholders that were never substituted.
# ANY bracket-delimited sequence is a placeholder — there is no legitimate use of
# [text], {text}, or <text> notation in conversational OpenRent tenant replies.
_PLACEHOLDER_RE = re.compile(r"\[[^\]]+\]|\{[^}]+\}")

# We never hand out an email address (no persona inbox exists), so ANY email in a
# reply is either a fabrication ("eleanor@example.com") or the landlord's echoed
# back — both are wrong. Reject it so it regenerates; the reply prompt redirects
# email requests to WhatsApp instead.
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def is_valid_reply(reply):

    if not reply:
        return False

    reply = reply.strip()

    # Too short
    if len(reply) < 3:
        return False

    # Too long
    if len(reply) > 1000:
        return False

    blocked_phrases = [

        "as an ai",

        "language model",

        "i cannot assist",

        "openai",

        "artificial intelligence"
    ]

    lower = reply.lower()

    for phrase in blocked_phrases:

        if phrase in lower:
            return False

    # Reject replies that contain unsubstituted template placeholders
    if _PLACEHOLDER_RE.search(reply):
        return False

    # Reject any email address — we never give one out (see _EMAIL_RE note).
    if _EMAIL_RE.search(reply):
        return False

    return True

def normalize_phone(number):
    return re.sub(r"\D", "", number or "")


def remove_unapproved_phone_numbers(reply, allowed_mobile_number=None):

    if not reply:
        return reply

    allowed_digits = normalize_phone(allowed_mobile_number)

    def replace(match):

        candidate = match.group(0).strip()

        # Keep ONLY the approved number, comparing on digits so the model may
        # write it however it likes ("07599 390 221" or "07599390221") and it
        # still survives. Any other number is stripped.
        if (
            allowed_digits
            and normalize_phone(candidate) == allowed_digits
        ):
            return candidate

        return ""

    sanitized = PHONE_LIKE_PATTERN.sub(
        replace,
        reply
    )

    sanitized = re.sub(
        r"\s+([.,!?;:])",
        r"\1",
        sanitized
    )

    sanitized = re.sub(
        r"[ \t]{2,}",
        " ",
        sanitized
    )

    return sanitized.strip()
