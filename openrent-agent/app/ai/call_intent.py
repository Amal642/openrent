"""Landlords trying to phone or text the WhatsApp number we gave them.

Our give-out numbers are WhatsApp Business lines: normal calls and SMS never
reach them, and WhatsApp voice calls cannot be answered either. Landlords still
try. In the 30 days to 2026-10-08, 99 threads had a landlord write something
like "called twice, not able to connect", "I texted your phone number, no
answer" or "I'll call you tomorrow" after we gave the number, and the model
answered badly: "Looking forward to your call" (the landlord then flagged us as
"not sufficiently responsive") or "could you send your number again? I didn't
get any messages".

The user's policy (2026-10-08): the give-out itself stays as it is. Only when
the landlord brings up calling or texting, steer them to a WhatsApp message in
the persona's voice, never saying "WhatsApp only":
  * they tried and failed -> "Really sorry, he must have been caught up. If you
    send him a quick WhatsApp message he'll reply as soon as he sees it."
  * they will call / ask to call -> "He can't always pick up during the day, so
    a quick WhatsApp message is the best way to reach him."

The situation is detected here in code and handed to the model as an exact
instruction (a general prompt rule leaks into replies where it does not
belong); replies.generate_reply then rejects any reply that agrees to a call.
"""
import re

from app.ai.personas import TENANT_SENDERS, tenant_shared_phone

TRIED = "tried"              # they called/texted the number and could not get through
WILL_CALL = "will_call"      # they say they will call/text it, or ask if they can
ASK_TO_CALL = "ask_to_call"  # they ask for our number so they can call (not given yet)

_APOS = "['’]"
_US = r"(?:you|him|her|them|your\s+(?:partner|husband|wife|other\s+half))"
# Without an "I"/"we" subject, "them" is usually someone else ("the team will call them").
_YOU = r"(?:you|him|her|your\s+(?:partner|husband|wife|other\s+half))"

# Already tried to call/text. An attempt phrase on its own counts ("I texted
# him", "called twice"); a failure phrase only with a phone word nearby, so
# "you didn't answer my question" is not mistaken for a failed call.
_ATTEMPT_RE = re.compile(
    rf"\b(?:i|we|i{_APOS}ve|we{_APOS}ve|have|has|he|she|just|already|also)\s+"
    rf"(?:called|rang|phoned|texted|sms{_APOS}?d|dialled|dialed)\b"
    rf"|^\s*(?:called|rang|phoned|texted)\b"
    rf"|\b(?:called|rang|phoned|texted)\s+(?:you|him|her|them|your|the\s+number|that\s+number|this\s+number|"
    rf"twice|again|several|many|a\s+few|earlier|yesterday|this\s+morning|but|and|no)\b"
    rf"|\btried\s+(?:calling|ringing|phoning|texting|to\s+(?:call|ring|phone|text|reach|contact|get\s+(?:hold\s+of|through)))\b"
    rf"|\b(?:gave|given)\s+{_US}\s+a\s+(?:call|ring|bell)\b"
    rf"|\bmissed\s+call\b|\bvoicemail\b",
    re.I | re.M,
)
_FAILURE_RE = re.compile(
    rf"\bno\s+(?:answer|response|reply|one\s+(?:answered|picked\s+up))\b"
    rf"|\b(?:not|isn{_APOS}?t|wasn{_APOS}?t)\s+(?:picking\s+up|answering|ringing|connecting|going\s+through|getting\s+through)\b"
    rf"|\b(?:didn{_APOS}?t|did\s+not|doesn{_APOS}?t|does\s+not|won{_APOS}?t|wouldn{_APOS}?t)\s+"
    rf"(?:pick\s+up|answer|ring|connect|go\s+through|get\s+through)\b"
    rf"|\b(?:can{_APOS}?t|cannot|couldn{_APOS}?t|unable\s+to)\s+(?:get\s+through|reach|connect|get\s+hold)\b"
    rf"|\b(?:number|phone|line)\s+(?:is\s+|was\s+)?(?:not\s+working|disconnected|dead|switched\s+off|off)\b",
    re.I,
)
_PHONE_WORD_RE = re.compile(r"\b(?:call\w*|ring\w*|phone\w*|text\w*|number|whats\s*app|line|dial\w*)\b", re.I)


def _tried(text) -> bool:
    return bool(_ATTEMPT_RE.search(text) or (_FAILURE_RE.search(text) and _PHONE_WORD_RE.search(text)))

# Says they will call/text, or asks whether they can. The object must be us
# (or omitted), never "the agent" / "my tenant": "I'll call the agent" is not this.
_VERB = r"(?:call|ring|phone|text|give\s+" + _US + r"\s+a\s+(?:call|ring|bell))"
_NOT_THIRD_PARTY = r"(?!\s+(?:the|my|our|his|their|a|an|back\s+the)\b)"
_WILL_CALL_RE = re.compile(
    rf"\b(?:i|we)\s*(?:{_APOS}ll|\s+will|\s+shall|{_APOS}m\s+going\s+to|\s+am\s+going\s+to|\s+can|\s+could|\s+would)\s+"
    rf"(?:just\s+|quickly\s+|then\s+|also\s+)?{_VERB}(?:\s+{_US})?\b{_NOT_THIRD_PARTY}"
    rf"|\b(?:can|could|shall|may|should)\s+(?:i|we)\s+(?:just\s+|quickly\s+)?{_VERB}(?:\s+{_US})?\b{_NOT_THIRD_PARTY}"
    rf"|\b(?:will|shall)\s+(?:give\s+{_YOU}\s+a\s+(?:call|ring|bell)|(?:call|ring|phone|text)\s+{_YOU})\b"
    rf"|\bis\s+it\s+(?:ok|okay|alright|fine)\s+(?:if\s+i|to)\s+(?:call|ring|phone|text)\b"
    rf"|\b(?:speak|talk|chat)\s+(?:on|over)\s+the\s+phone\b"
    rf"|\b(?:have|do)\s+a\s+(?:quick\s+)?(?:phone\s+)?call\b"
    rf"|\bwhat\s+time\s+(?:is\s+(?:good|best)|suits|works)\s+(?:to|for\s+a)\s+(?:call|ring|chat)\b",
    re.I,
)

# Asking for OUR number in order to call/text (before we have given it).
_ASK_NUMBER_RE = re.compile(
    rf"\byour\s+(?:phone\s+|mobile\s+|contact\s+)?(?:number|mobile|digits)\b"
    rf"|\ba\s+(?:phone\s+|mobile\s+|contact\s+)?number\s+(?:for|to|i\s+can|we\s+can)\b"
    rf"|\bhow\s+(?:can|do|should)\s+i\s+(?:reach|contact|get\s+hold\s+of)\s+{_US}\b",
    re.I,
)
_CALL_WORD_RE = re.compile(r"\b(?:call|ring|phone\s+(?:you|him|her)|text|speak|talk)\b", re.I)

# The landlord is at the property waiting right now (not "I will be at the
# property for 6:30"): the reply must withdraw, not steer to WhatsApp.
_AT_PROPERTY_NOW_RE = re.compile(
    rf"\b(?:i{_APOS}?m|i\s+am|we{_APOS}?re|we\s+are)\s+(?:now\s+|already\s+|just\s+)?"
    rf"(?:at\s+the\s+(?:property|flat|house|building|door)|outside|here|waiting)\b"
    rf"|\bwaiting\s+(?:for\s+you|outside)\b|\b(?:here|outside)\s+now\b",
    re.I,
)
_UK_MOBILE_RE = re.compile(r"(?:\+?44\s?7|\b07)(?:[\s.\-]?\d){9}\b")
_NUMBER_REMOVED_RE = re.compile(r"\(\s*number\s+removed\s*\)", re.I)


def _sender(message) -> str:
    return str(message.get("sender") or message.get("direction") or "").lower()


def _content(message) -> str:
    return str(message.get("message") or message.get("content") or message.get("text") or "")


def _is_ours(message) -> bool:
    return _sender(message) in TENANT_SENDERS


def _we_gave_number(message, mobile_number) -> bool:
    text = _content(message)
    if mobile_number and tenant_shared_phone([{"sender": "us", "message": text}], mobile_number):
        return True
    # Without a known give-out number (or when the scraped thread shows ours
    # redacted), any mobile or "(Number Removed)" in our own message counts.
    return bool(_UK_MOBILE_RE.search(text) or _NUMBER_REMOVED_RE.search(text))


def call_state(messages, mobile_number=None):
    """How the next reply must handle a landlord calling/texting our number,
    or None. Looks only at the landlord's messages since our last message."""
    msgs = [m for m in (messages or []) if isinstance(m, dict)]
    last_ours = max((i for i, m in enumerate(msgs) if _is_ours(m)), default=-1)
    new_landlord = [_content(m) for m in msgs[last_ours + 1:] if not _is_ours(m)]
    if not new_landlord:
        return None
    # At the property / on their way right now: the withdraw-from-the-viewing
    # rule owns that reply. Sampling showed the steer winning instead ("We're
    # still coming Tuesday at 5:45" to a landlord standing at the door).
    text = " ".join(new_landlord)
    if _AT_PROPERTY_NOW_RE.search(text):
        return None
    gave = any(_is_ours(m) and _we_gave_number(m, mobile_number) for m in msgs)
    if gave:
        if _tried(text):
            return TRIED
        if _WILL_CALL_RE.search(text):
            return WILL_CALL
        return None
    if mobile_number and _ASK_NUMBER_RE.search(text) and _CALL_WORD_RE.search(text):
        return ASK_TO_CALL
    return None


# Example lines in the user's agreed style, picked per thread so the fleet does
# not all send one identical sentence (sampling: the model copied a single example
# verbatim). {p} is the partner's name; the model is told to use their pronoun.
_TRIED_LINES = (
    "Really sorry, {p} must have been caught up. If you send {p} a quick WhatsApp message you'll get a reply as soon as it's seen.",
    "So sorry about that, {p}'s had a hectic day. Best to drop {p} a WhatsApp message instead and you'll hear back as soon as it's seen.",
    "Apologies, {p} must have been tied up. A quick WhatsApp message to {p} is the easiest way, you'll get a reply as soon as it's seen.",
    "Sorry about that, {p} must have been in the middle of something. If you pop {p} a WhatsApp message you'll hear back shortly.",
)
_WILL_CALL_LINES = (
    "{p} can't always pick up during the day, so a quick WhatsApp message is the best way to reach {p}, you'll get a reply as soon as it's seen.",
    "Just so you know, {p} isn't always free to pick up, so a WhatsApp message works best and you'll hear back quickly.",
    "Calls can be hit and miss with {p} during the day, so it's easiest to drop {p} a WhatsApp message and you'll get a reply as soon as it's seen.",
)
_SELF_TRIED_LINES = (
    "Really sorry, I must have been caught up. If you send me a quick WhatsApp message I'll reply as soon as I see it.",
    "So sorry, I've had a hectic day. Best to drop me a WhatsApp message instead and I'll get straight back to you.",
)
_SELF_WILL_CALL_LINES = (
    "I can't always pick up during the day, so a quick WhatsApp message is the best way to reach me, I'll reply as soon as I see it.",
    "Calls can be hit and miss with me during the day, so a WhatsApp message is easiest and I'll get back to you quickly.",
)
_PARTNER_WORD_RE = re.compile(r"\b(?:partner|husband|wife|other\s+half)\b", re.I)


def number_is_partners(messages, mobile_number=None, partner_name=None) -> bool:
    """Whose number did we give? Current give-outs always say "my partner's
    WhatsApp"; some older threads said "you can reach me on WhatsApp"."""
    for m in reversed([m for m in (messages or []) if isinstance(m, dict)]):
        if _is_ours(m) and _we_gave_number(m, mobile_number):
            text = _content(m)
            if _PARTNER_WORD_RE.search(text):
                return True
            if partner_name and re.search(rf"\b{re.escape(partner_name)}\b", text, re.I):
                return True
            return False
    return True


def _pick(lines, seed):
    return lines[sum(ord(c) for c in str(seed or "")) % len(lines)]


def prompt_instruction(state, mobile_number=None, partner_name=None, seed="", partners=True) -> str:
    """Exact instruction for the reply prompt. Wording agreed with the user."""
    never = (
        "Never say the number is \"WhatsApp only\" and never say calls or texts do not work on "
        "it. Never agree to a phone call, never say you look forward to their call, and never "
        "say you or your partner will call them. Do not ask them to resend their number or "
        "anything else here."
    )
    p = partner_name or "my partner"
    who = f"your partner {partner_name}" if partner_name else "your partner"
    pronoun = (
        f" Use {partner_name}'s name or the right pronoun for {partner_name}, never a wrong one."
        if partner_name else ""
    )
    vary = "Say it in your own words in that spirit; do not copy the example word for word."
    if state == TRIED:
        if not partners:
            return (
                "- RIGHT NOW: the landlord says they tried to call or text the WhatsApp number you "
                "gave them (your own) and could not get through. Apologise warmly and briefly, say "
                "you must have been caught up, and ask them to send you a quick WhatsApp message "
                "instead, which you will reply to as soon as you see it. If they already sent a "
                "WhatsApp message, say you will get back to them on it shortly. For example: "
                f"\"{_pick(_SELF_TRIED_LINES, seed)}\" {vary} {never} Then answer anything else they asked."
            )
        return (
            f"- RIGHT NOW: the landlord says they tried to call or text the number you gave "
            f"({who}'s WhatsApp) and could not get through. Apologise warmly and briefly, say "
            f"{p} must have been caught up, and ask them to send {p} a quick WhatsApp message "
            f"instead, which will get a reply as soon as it is seen. If they say they already sent "
            f"a WhatsApp message, say {p} will get back to them on it shortly. For example: "
            f"\"{_pick(_TRIED_LINES, seed).format(p=p)}\" {vary}{pronoun} {never} "
            "Then answer anything else they asked."
        )
    if state == WILL_CALL:
        if not partners:
            return (
                "- RIGHT NOW: the landlord says they will call or text the WhatsApp number you gave "
                "them (your own), or asks if they can. Steer them to a message instead: you cannot "
                "always pick up during the day, so a quick WhatsApp message is the best way to reach "
                f"you. For example: \"{_pick(_SELF_WILL_CALL_LINES, seed)}\" {vary} {never} "
                "Then answer anything else they asked."
            )
        return (
            f"- RIGHT NOW: the landlord says they will call or text the number you gave ({who}'s "
            f"WhatsApp), or asks if they can. Steer them to a message instead: {p} cannot always "
            f"pick up during the day, so a quick WhatsApp message is the best way to reach {p}. "
            f"For example: \"{_pick(_WILL_CALL_LINES, seed).format(p=p)}\" {vary}{pronoun} "
            f"{never} Then answer anything else they asked."
        )
    if state == ASK_TO_CALL and mobile_number:
        return (
            f"- RIGHT NOW: the landlord wants a number so they can call. When you give {who}'s "
            f"WhatsApp {mobile_number}, add that {p} cannot always pick up during the day, so a "
            f"WhatsApp message is the quickest way to reach {p}.{pronoun} {never}"
        )
    return ""


# A reply that invites or accepts a phone call (or an SMS) on a line that
# cannot take one. "Text him on WhatsApp" is what we want, so a "text" that is
# followed by WhatsApp in the same sentence does not count.
_TEXT_NOT_WA = r"text(?![^.?!\n]{0,30}whats\s*app)"
_AGREES_TO_CALL_RE = re.compile(
    rf"\blook(?:ing)?\s+forward\s+to\s+(?:your|the|a)\s+(?:call|ring|phone\s+call)\b"
    rf"|\b(?:speak|talk|chat)\s+(?:to\s+you\s+)?(?:soon\s+|later\s+|then\s+)?(?:on|over)\s+the\s+phone\b"
    rf"|\b(?:feel\s+free\s+to|happy\s+for\s+you\s+to|you\s+(?:can|could))\s+"
    rf"(?:call|ring|phone|{_TEXT_NOT_WA}|give\s+(?:me|him|her|us|them)\s+a\s+(?:call|ring|bell))\b"
    rf"|\bjust\s+(?:call|ring|phone)\s+(?:me|him|her|us)\b"
    rf"|\b(?:call|ring|phone)\s+(?:me|him|her|us)\s+(?:any\s?time|whenever|on|at|when|if)\b"
    rf"|\bgive\s+(?:me|him|her|us)\s+a\s+(?:call|ring|bell)\b"
    rf"|\b(?:answer|pick\s+up)\s+(?:the\s+phone|your\s+call|the\s+call|when\s+you\s+(?:call|ring)|if\s+you\s+(?:call|ring))\b"
    rf"|\btake\s+(?:your|the|a)\s+call\b"
    rf"|\bbe\s+(?:free|available)\s+(?:to|for\s+a)\s+(?:phone\s+)?(?:call|talk\s+on\s+the\s+phone)\b"
    rf"|\b(?:i|he|she|we|my\s+partner)\s*(?:{_APOS}ll|\s+will)\s+(?:call|ring|phone)\s+you\b"
    rf"|\b(?:a\s+)?call\s+(?:is|would\s+be|sounds)\s+(?:fine|great|good|perfect)\b"
    rf"|\b(?:work|works|suit|suits|free|good|fine)\s+(?:well\s+)?for\s+a\s+(?:quick\s+)?(?:phone\s+)?call\b"
    rf"|\bwait(?:ing)?\s+for\s+your\s+call\b|\blook\s+out\s+for\s+your\s+call\b",
    re.I,
)


def reply_agrees_to_call(reply) -> bool:
    return bool(_AGREES_TO_CALL_RE.search(str(reply or "")))


def strip_call_sentences(reply) -> str:
    parts = re.split(r"(?<=[.!?])\s+", str(reply or "").strip())
    return " ".join(p for p in parts if p and not reply_agrees_to_call(p)).strip()


# Is the landlord trying to reach us right now? Then the human-like reply delay
# must not hold the answer (they are waiting on the phone or at the door).
_URGENT_RE = re.compile(
    r"\b(?:now|right\s+now|just\s+now|in\s+a\s+(?:moment|minute|sec|bit)|shortly|"
    r"(?:in|within)\s+\d+\s*(?:min|mins|minutes)|here|outside|at\s+the\s+(?:property|flat|door|house))\b",
    re.I,
)


def call_needs_fast_reply(messages, mobile_number=None) -> bool:
    state = call_state(messages, mobile_number)
    if state == TRIED:
        return True
    if state == WILL_CALL:
        msgs = [m for m in (messages or []) if isinstance(m, dict)]
        last_ours = max((i for i, m in enumerate(msgs) if _is_ours(m)), default=-1)
        text = " ".join(_content(m) for m in msgs[last_ours + 1:] if not _is_ours(m))
        return bool(_URGENT_RE.search(text))
    return False
