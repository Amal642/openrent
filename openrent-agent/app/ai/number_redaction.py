"""Landlord numbers that OpenRent redacted out of the chat.

OpenRent strips phone numbers typed into a thread and shows "(Number Removed)"
instead (WhatsApp links become "(URL Removed)"). Once that has happened, asking
the landlord for their number again is pointless (it is stripped again) and
reads as not having read their message, and saying "thanks, I've saved your
number" is a lie that kills the lead: the landlord thinks we have it and never
tries again. The only working move is to give OUR WhatsApp so they message us
there, and their number arrives that way.

Prod, 7 days to 2026-10-07: of 61 threads we answered after a redacted number,
~12 re-asked AND gave ours, ~6 re-asked or claimed to have saved it without
giving ours. This module is the single source of truth for detecting the case
and for checking a reply against it; replies.generate_reply enforces it and the
human reply prompt explains it to the model.
"""
import re

from app.ai.personas import TENANT_SENDERS, tenant_shared_phone

_NUMBER_REMOVED_RE = re.compile(r"\(\s*number\s+removed\s*\)", re.I)
_URL_REMOVED_RE = re.compile(r"\(\s*url\s+removed\s*\)", re.I)
_WHATSAPP_RE = re.compile(r"whats\s*app|\bwa\.me\b", re.I)

# Policy states, from redaction_state().
GIVE = "give"            # their number was blocked, we have never given ours
REMIND = "remind"        # blocked again after we gave ours: point them to it again
SHARED = "shared"        # we already gave ours after their latest blocked number
NO_MOBILE = "no_mobile"  # blocked, but this account has no give-out number


def text_has_blocked_number(text) -> bool:
    """True if a landlord message shows a phone number (or a WhatsApp link)
    that OpenRent redacted."""
    text = str(text or "")
    if _NUMBER_REMOVED_RE.search(text):
        return True
    return bool(_URL_REMOVED_RE.search(text) and _WHATSAPP_RE.search(text))


def _sender(message) -> str:
    return str(message.get("sender") or message.get("direction") or "").lower()


def _content(message) -> str:
    return str(message.get("message") or message.get("content") or message.get("text") or "")


def _is_landlord(message) -> bool:
    sender = _sender(message)
    return bool(sender) and sender not in TENANT_SENDERS


def landlord_number_blocked(messages) -> bool:
    """True if any landlord message in the thread had its number redacted."""
    return any(
        isinstance(m, dict) and _is_landlord(m) and text_has_blocked_number(_content(m))
        for m in messages or []
    )


def redaction_state(messages, mobile_number):
    """How the next reply must handle a redacted landlord number, or None when
    no landlord number was ever redacted in this thread."""
    last_blocked = last_ours = -1
    for i, m in enumerate(messages or []):
        if not isinstance(m, dict):
            continue
        if _is_landlord(m):
            if text_has_blocked_number(_content(m)):
                last_blocked = i
        elif (mobile_number and tenant_shared_phone([m], mobile_number)) or (
            # The scraped thread can show OUR give-out redacted too; it still
            # counts as given, or every reply would re-give the number.
            _NUMBER_REMOVED_RE.search(_content(m))
        ):
            last_ours = i
    if last_blocked < 0:
        return None
    if not mobile_number:
        return NO_MOBILE
    if last_ours < 0:
        return GIVE
    return REMIND if last_blocked > last_ours else SHARED


# "WORD:" speaker prefix of format_conversation (optionally timestamped).
_SPEAKER_RE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?([A-Za-z_]+):\s?(.*)$")
_KNOWN_SPEAKERS = TENANT_SENDERS | {"landlord", "owner", "inbound", "you", "me"}


def parse_conversation_text(text):
    """Split format_conversation() output back into messages. A message can span
    several lines (signatures, lists), so a line only starts a new message when
    it begins with a known speaker prefix; anything else continues the previous
    message. Line-by-line checks missed "(Number Removed)" in signatures."""
    messages = []
    for line in str(text or "").splitlines():
        match = _SPEAKER_RE.match(line)
        if match and match.group(1).lower() in _KNOWN_SPEAKERS:
            speaker = match.group(1).lower()
            if speaker in ("you", "me"):
                speaker = "us"
            messages.append({"sender": speaker, "message": match.group(2)})
        elif messages:
            messages[-1]["message"] += "\n" + line
    return messages


_APOS = "['’]"
_CONTACT = r"(?:number|mobile|phone number|contact number|digits)"
# "your number doesn't come through" describes the block; it is not an ask/claim.
_NOT_SUBJECT = (
    r"(?!\s+(?:does|did|is|was|has|gets|got|came|comes|keeps|won|can|isn|wasn|doesn|didn|"
    r"hasn|still|just|seems|appears|never|always|might|may|will|would|wo|ca)\b)"
)
_NEGATION_RE = re.compile(rf"n{_APOS}t\b|\bnot\b|\bnever\b|\bno\b|\bcannot\b", re.I)

# Asking the landlord for their number (again).
_ASKS_THEIR_NUMBER_RE = re.compile(
    rf"\b(?:send|share|pop|drop|give|text|post|type|write|leave|put|resend|re-send)\b[^.?!\n]{{0,25}}"
    rf"\byour\b[^.?!\n]{{0,12}}\b(?:{_CONTACT}|whats\s*app)\b{_NOT_SUBJECT}"
    rf"|\b(?:could|can|may|might)\s+(?:i|we)\s+(?:get|grab|have|take)\s+(?:your|the|that|a)\s+"
    rf"(?:\w+\s+)?{_CONTACT}\b"
    rf"|\bwhat{_APOS}?s\s+your\s+{_CONTACT}|\bwhat\s+is\s+your\s+{_CONTACT}"
    rf"|\b(?:number|mobile|digits)\s+again\b"
    rf"|\b(?:send|share|post|type|try)\w*\s+(?:it|that)\s+(?:again|once more|over again)\b"
    rf"|\bre-?send\b",
    re.I,
)

# Claiming we received, or will use, a number we never got.
_CLAIMS_THEIR_NUMBER_RE = re.compile(
    rf"\b(?:save|saved|got|have|note|noted|received|add|added|store|stored|taken|keep|use|pass|passed|"
    rf"passing|forward|forwarded|send|sent|give|given)\s+(?:on\s+)?your\s+{_CONTACT}\b{_NOT_SUBJECT}"
    rf"|\bthanks?\b[^.?!\n]{{0,20}}\byour\s+{_CONTACT}\b{_NOT_SUBJECT}"
    rf"|\bthanks?\s+for\s+(?:sharing|sending|the)\b[^.?!\n]{{0,15}}\b{_CONTACT}\b"
    rf"|\bon\s+(?:that|this|the|your)\s+{_CONTACT}\b{_NOT_SUBJECT}"
    rf"|\b(?:i|we|my partner|he|she|they)(?:{_APOS}ll|\s+will|\s+can|\s+am going to|\s+are going to|"
    rf"\s+is going to)\s+(?:give\s+(?:you|him|her|them)\s+a\s+(?:call|ring|bell|text)"
    rf"|(?:call|ring|text|whatsapp)\s+(?:you|him|her|them)\b"
    rf"|(?:message|contact|drop)\s+(?:you|him|her|them)\b[^.?!\n]{{0,20}}"
    rf"(?:on\s+whats\s*app|on\s+(?:that|this|the|your)\s+{_CONTACT}|directly|by phone|\bthere\b))",
    re.I,
)


def _claims_their_number(text: str) -> bool:
    for match in _CLAIMS_THEIR_NUMBER_RE.finditer(text):
        # "I didn't get your number" / "I haven't got your number" are honest.
        window = text[max(0, match.start() - 15):match.end()]
        if not _NEGATION_RE.search(window):
            return True
    return False


def reply_redaction_violations(reply) -> list[str]:
    """Reasons a reply is wrong for a thread whose landlord number was redacted:
    asking for their number again, or claiming to have / use it."""
    reasons = []
    text = str(reply or "")
    if _ASKS_THEIR_NUMBER_RE.search(text):
        reasons.append("asks_their_number")
    if _claims_their_number(text):
        reasons.append("claims_their_number")
    return reasons


def strip_violating_sentences(reply) -> str:
    """Drop only the sentences that re-ask for / claim the landlord's number."""
    parts = re.split(r"(?<=[.!?])\s+", str(reply or "").strip())
    kept = [p for p in parts if p and not reply_redaction_violations(p)]
    return " ".join(kept).strip()


_GIVEOUT_LINES = (
    "Your number doesn't come through on here unfortunately, OpenRent blocks them. "
    "My partner's WhatsApp is {mobile}, they're sorting the viewing side, so best to message them there.",
    "Ah your number gets blocked on here. Easiest is to message my partner on WhatsApp "
    "on {mobile}, they're handling the viewings.",
    "Your number didn't come through, OpenRent hides them on here. My partner's on WhatsApp at "
    "{mobile} and is sorting the viewing, so feel free to message them there.",
)


def redacted_giveout_line(mobile_number, seed: str = "") -> str:
    """A give-out line for a landlord whose number was redacted. Varied per
    thread (seed) so accounts do not all send the identical sentence."""
    idx = sum(ord(c) for c in str(seed or "")) % len(_GIVEOUT_LINES)
    return _GIVEOUT_LINES[idx].format(mobile=mobile_number)


NO_MOBILE_LINE = (
    "Your number doesn't come through on here unfortunately, OpenRent blocks them, "
    "so happy to keep sorting things here."
)


def prompt_instruction(state, mobile_number) -> str:
    """Exact instruction for the reply prompt in a redacted-number thread."""
    never = (
        "Do NOT ask for their number again or ask them to resend it, in any wording, "
        "because OpenRent blocks it every time. Do NOT say you have saved, noted, got or "
        "will pass on their number, and do not say you or your partner will call, text or "
        "message them, because their number never reached you."
    )
    if state == GIVE:
        return (
            "- RIGHT NOW: the landlord already tried to give you their number but OpenRent "
            "blocked it (it shows as \"(Number Removed)\"), so it never reached you. In this "
            "reply say briefly that it does not come through on here and give your partner's "
            f"WhatsApp number {mobile_number} (your partner is sorting the viewings) so they can "
            f"message your partner there. {never} Then answer anything else they asked."
        )
    if state == REMIND:
        return (
            "- RIGHT NOW: the landlord tried to send their number again and OpenRent blocked it "
            "again, so it still has not reached you. Say briefly that numbers do not come through "
            f"on here and that the easiest way is to message your partner on WhatsApp at "
            f"{mobile_number}. {never} Then answer anything else they asked."
        )
    if state == SHARED:
        return (
            "- The landlord's number was blocked by OpenRent earlier and you have already given "
            f"your partner's WhatsApp. {never} Just carry on with the conversation."
        )
    if state == NO_MOBILE:
        return (
            "- The landlord's number was blocked by OpenRent, so it never reached you. "
            f"{never} If it comes up, say numbers do not come through on here and carry on "
            "arranging things here."
        )
    return ""
