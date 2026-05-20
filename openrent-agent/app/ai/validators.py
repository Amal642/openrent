import re


PHONE_LIKE_PATTERN = re.compile(
    r"(?<!\w)(?:\+44[\d\s().-]{8,}\d|44[\d\s().-]{8,}\d|0[1-9]\d[\d\s().-]{6,}\d)(?!\w)"
)


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

    return True

def normalize_phone(number):
    return re.sub(r"\D", "", number or "")


def remove_unapproved_phone_numbers(reply, allowed_mobile_number=None):

    if not reply:
        return reply

    allowed_normalized = normalize_phone(
        allowed_mobile_number
    )

    def replace(match):

        candidate = match.group(0).strip()

        candidate_normalized = normalize_phone(
            candidate
        )

        # Keep ONLY approved number
        if (
            allowed_normalized
            and candidate_normalized == allowed_normalized
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