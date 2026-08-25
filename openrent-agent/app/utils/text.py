"""Small, dependency-free text helpers for outbound messages."""
import re

# Em dash (\u2014) and horizontal bar (\u2015) are strong "written by an AI"
# tells in casual chat; landlords read them as bot behaviour. Every outbound
# message is scrubbed of them before it is typed/sent.
_EM_DASH_RE = re.compile(r"\s*[\u2014\u2015]\s*")


def strip_ai_dashes(text):
    """Make a message read as if a person typed it.

    - em dash / horizontal bar  -> ", " (surrounding whitespace collapsed)
    - en dash (\u2013)           -> "-"  (plain hyphen; keeps ranges like 3-5pm)

    Safe on None/empty. Idempotent.
    """
    if not text:
        return text
    text = _EM_DASH_RE.sub(", ", text)
    text = text.replace("\u2013", "-")
    return text
