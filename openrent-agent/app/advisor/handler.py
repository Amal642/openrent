"""
Main entry point for the AI Advisor.
Classifies the question and routes to the appropriate handler.
"""

import re

from app.advisor.guide_parser import search_guide
from app.advisor.stats_service import answer_stats_question
from app.advisor.recommendation_engine import generate_recommendation
from app.advisor.area_intelligence import answer_area_question, area_metrics_summary


# ---------------------------------------------------------------------------
# Identity response
# ---------------------------------------------------------------------------

_IDENTITY_RESPONSE = (
    "I am the Land Royal Operations Advisor — an AI assistant built specifically "
    "for managing your UK rental outreach platform.\n\n"
    "I can help you with:\n\n"
    "**Platform Statistics**\n"
    "• Current account counts, active and disabled\n"
    "• Today's outreach numbers, reply rates, and phone numbers collected\n"
    "• Proxy health and capacity summaries\n\n"
    "**Troubleshooting**\n"
    "• Step-by-step fixes for account, proxy, messaging, and listing issues\n"
    "• Guidance drawn from the platform's built-in troubleshooting guide\n\n"
    "**Operational Recommendations**\n"
    "• How many accounts and SIMs are needed for a given area\n"
    "• Which cities or boroughs to target next\n"
    "• Coverage planning and scaling advice\n\n"
    "**UK Rental Knowledge**\n"
    "• Tenancy terms, landlord-tenant concepts, and OpenRent platform questions\n\n"
    "I only answer questions about this platform and UK property operations. "
    "I do not browse the internet, write code, or answer general knowledge questions."
)

_REFUSAL_RESPONSE = (
    "I can only help with OpenRent operations, platform troubleshooting, account management, "
    "listing coverage, messaging performance, and UK rental property related questions.\n\n"
    "Try asking something related to accounts, listings, proxies, coverage planning, "
    "landlord conversations, or platform operations."
)


# ---------------------------------------------------------------------------
# Domain scope patterns
# ---------------------------------------------------------------------------

_IDENTITY_PATTERNS = [
    r"\bwho\s+are\s+you\b",
    r"\bwhat\s+are\s+you\b",
    r"\bwhat\s+(?:can\s+you|do\s+you)\s+(?:do|help)\b",
    r"\bwhat\s+is\s+your\s+(?:name|purpose|role)\b",
    r"\byour\s+(?:name|role|purpose)\b",
    r"\bintroduce\s+yourself\b",
    r"\btell\s+me\s+about\s+yourself\b",
    r"\bwhat\s+(?:kind\s+of\s+)?(?:ai|bot|assistant)\s+are\s+you\b",
    r"\bwhat\s+are\s+your\s+capabilit",
    r"\bwhat\s+can\s+(?:i|we)\s+ask\b",
]

_OUT_OF_SCOPE_PATTERNS = [
    # Food & cooking
    r"\brecipe(?:s)?\b", r"\bcook(?:ing|ed)?\b", r"\bbak(?:e|ing)\b",
    r"\bingredient(?:s)?\b", r"\bdish(?:es)?\s+to\s+make\b",
    r"\brestaurant(?:s)?\b", r"\bchicken\s+curry\b", r"\bdessert\b",
    # General programming / dev help (not platform-related)
    r"\bflutter\b", r"\bandroid\s+app\b", r"\bios\s+app\b",
    r"\bwrite\s+(?:a\s+)?(?:function|class|script|program|algorithm)\b",
    r"\bhelp\s+(?:me\s+)?(?:with\s+)?(?:coding|programming|debugging)\b",
    r"\bwrite\s+(?:a\s+)?(?:flutter|django|react|vue|node|swift|kotlin|java|php|ruby|rust)\b",
    # General world knowledge
    r"\bcapital\s+(?:city\s+)?of\s+\w+\b",
    r"\bwhat\s+(?:is\s+the\s+)?flag\s+of\b",
    r"\bwho\s+(?:won|invented|discovered|wrote|painted|composed)\b",
    r"\bhistory\s+of\b",
    # Finance / markets
    r"\bstock\s+(?:market|price|tip)\b",
    r"\bcrypto(?:currency)?\b", r"\bbitcoin\b", r"\bethereum\b",
    r"\binvest(?:ment|ing)?\s+(?:advice|tip|strategy)\b",
    r"\bshare\s+price\b", r"\bforex\b",
    # Medical
    r"\bmedical\s+advice\b", r"\bsymptom(?:s)?\s+of\b",
    r"\bprescription\b", r"\bdiagnos[ei]\b",
    r"\bdoctor\s+(?:advice|recommend)\b", r"\bdrug\s+dose\b",
    # Travel
    r"\bflight\s+(?:to|from|price|booking)\b",
    r"\bhotel\s+(?:in|near|booking|recommend)\b",
    r"\bvisa\s+(?:for|requirement|apply)\b",
    r"\btravel\s+(?:to|advice|tips|itinerary)\b",
    # Weather
    r"\bweather\s+(?:today|tomorrow|forecast|in)\b",
    r"\bwill\s+it\s+rain\b",
    # Generic chatbot usage
    r"\btell\s+me\s+a\s+(?:story|joke|poem|fun\s+fact)\b",
    r"\bwrite\s+(?:an?\s+)?(?:essay|poem|story|song|letter\s+to)\b",
    r"\btranslate\s+(?:this|to|from)\b",
    # Personal
    r"\bdating\s+(?:advice|app|tip)\b",
    r"\brelationship\s+advice\b",
    r"\bweight\s+loss\b", r"\bdiet\s+plan\b",
    r"\bhoroscope\b", r"\bstar\s+sign\b",
]

# If ANY of these words are in the message the question is always in scope
_IN_SCOPE_SIGNALS = [
    r"\baccounts?\b", r"\bprox(?:y|ies)\b", r"\blistings?\b",
    r"\bmessage(?:s|ing)?\b", r"\bleads?\b", r"\bsims?\b",
    r"\bopenrent\b", r"\blandlord(?:s)?\b", r"\btenant(?:s)?\b",
    r"\bpropert(?:y|ies)\b", r"\bworker(?:s)?\b", r"\bcoverage\b",
    r"\boutreach\b", r"\bphone\s*number(?:s)?\b",
    r"\b(?:london|birmingham|manchester|leeds|sheffield|bristol|liverpool|nottingham|glasgow|edinburgh)\b",
    r"\bplatform\b", r"\bdashboard\b", r"\boperations?\b",
    r"\bguarantor\b", r"\bdeposit\b", r"\btenancy\b",
    r"\bletting(?:s)?\b", r"\brenter(?:s)?\b", r"\brent(?:al)?\b",
    r"\buk\s+rental\b", r"\bourreach\b",
    r"\bborough(?:s)?\b", r"\bcoverage\b",
]


def _is_identity_question(text: str) -> bool:
    return any(re.search(p, text) for p in _IDENTITY_PATTERNS)


def _is_out_of_scope(text: str) -> bool:
    has_in_scope_signal = any(re.search(p, text) for p in _IN_SCOPE_SIGNALS)
    if has_in_scope_signal:
        return False
    return any(re.search(p, text) for p in _OUT_OF_SCOPE_PATTERNS)


# ---------------------------------------------------------------------------
# Classification patterns
# ---------------------------------------------------------------------------

_REC_PATTERNS = [
    r"\bhow\s+many\s+(?:sims?|accounts?)\s+(?:do\s+(?:we\s+)?need|are\s+needed|(?:would\s+be\s+)?required?)\b",
    r"\bhow\s+long\s+(?:will|would)\s+it\s+take\b",
    r"\bwhich\s+area\s+should\b",
    r"\bshould\s+we\s+(?:add|target|expand|use|open)\b",
    r"\bneed\s+more\s+accounts?\b",
    r"\bhow\s+many\s+accounts?\s+(?:do\s+we\s+need|would\s+(?:we\s+)?need|are\s+(?:needed|required?))\b",
    r"\bhow\s+many\s+accounts?\s+(?:for|to\s+cover)\b",
    r"\bcoverage\b",
    r"\bunderserved\b",
    r"\brecommend(?:ation)?\b",
    r"\bscale\s+(?:up|to)\b",
    r"\bbest\s+(?:area|city|approach|strategy)\b",
    r"\bnext\s+(?:area|city|location)\s+(?:to\s+target|should)\b",
    r"\bexpand\s+to\b",
    r"\bcover\s+(?:all\s+of\s+)?(?:birmingham|manchester|london|leeds|sheffield|bristol|liverpool|nottingham|glasgow|edinburgh)\b",
]

_STATS_PATTERNS = [
    r"\bhow\s+many\b",
    r"\bcount\b",
    r"\btotal\s+(?:accounts?|messages?|leads?|phones?|proxies?|numbers?)\b",
    r"\bactive\s+accounts?\b",
    r"\bdisabled\s+accounts?\b",
    r"\bmessages?\s+sent\b",
    r"\bnew\s+(?:listings?|contacts?)\s+today\b",
    r"\blistings?\s+found\s+today\b",
    r"\bproxies?\s+(?:are\s+)?(?:failing|down|degraded|healthy)\b",
    r"\breply\s+rate\b",
    r"\bphones?\s+(?:collected|captured|today)\b",
    r"\bplatform\s+status\b",
    r"\bwhat'?s?\s+(?:our\s+)?(?:status|progress|performance)\b",
    r"\btoday'?s?\s+(?:numbers?|stats?|progress)\b",
]

_TROUBLE_PATTERNS = [
    r"\bproxy\s+(?:down|degraded|failing|not\s+working|error)\b",
    r"\bproxies?\s+(?:down|degraded|failing)\b",
    r"\bprox(?:y|ies)\s+degraded\b",
    r"\b(?:login|session)\s+(?:failed?|expired?|error)\b",
    r"\baccount\s+(?:disabled?|suspended?|stuck|failed?|banned?|not\s+working|cannot\s+log)\b",
    r"\bno\s+(?:messages?\s+sent|listings?\s+found|replies?)\b",
    r"\bwhy\s+(?:is|are|isn'?t|aren'?t|doesn'?t|don'?t)\b",
    r"\bnot\s+(?:sending|working|loading|connecting)\b",
    r"\bfailed?\s+to\s+(?:send|login|connect|load)\b",
    r"\bstuck\b",
    r"\bcaptcha\b",
    r"\bsuspended?\b",
    r"\bverification\s+(?:required?|failed?)\b",
    r"\bconnection\s+(?:timeout|error|failed?)\b",
    r"\btunnel\s+error\b",
    r"\blow\s+(?:reply\s+rate|listing\s+count|message\s+count)\b",
    r"\bhigh\s+(?:failure|error)\s+rate\b",
    r"\bduplicate\s+(?:messages?|listings?|conversations?)\b",
    r"\bsession\s+expired?\b",
    r"\bwhat\s+(?:does\s+this\s+mean|is\s+wrong)\b",
    r"\bfix\b.*\b(proxy|account|message|listing)\b",
    r"\b(proxy|account|login|message)\b.*\bfix\b",
    r"\blow\s+messages?\b",
    r"\bno\s+messages?\b",
]


def _classify(message: str) -> str:
    text = message.lower().strip()

    rec_score = sum(1 for p in _REC_PATTERNS if re.search(p, text))
    stats_score = sum(1 for p in _STATS_PATTERNS if re.search(p, text))
    trouble_score = sum(1 for p in _TROUBLE_PATTERNS if re.search(p, text))

    if rec_score > 0:
        return "recommendation"
    if trouble_score > 0 and trouble_score >= stats_score:
        return "troubleshooting"
    if stats_score > 0:
        return "stats"
    return "troubleshooting"  # default — guide usually has something useful


_LOCATION_PATTERN = re.compile(
    r"\b(croydon|brixton|clapham|wandsworth|battersea|lewisham|greenwich|bromley|"
    r"streatham|dulwich|tooting|camberwell|peckham|kingston|wimbledon|sutton|"
    r"merton|lambeth|southwark|woolwich|bexley|bexleyheath|sidcup|"
    r"putney|norwood|upper norwood|hanworth|london)\b",
    re.I,
)


def handle_chat(message: str) -> dict:
    text = message.lower().strip()

    # Identity check — must come before scope check
    if _is_identity_question(text):
        return {"type": "info", "response": _IDENTITY_RESPONSE}

    # Domain scope check — refuse anything clearly off-topic
    if _is_out_of_scope(text):
        return {"type": "out_of_scope", "response": _REFUSAL_RESPONSE}

    # Area intelligence takes priority: if we can answer deterministically from
    # real coverage data, return that before any classification or LLM call.
    area_answer = answer_area_question(message)
    if area_answer:
        return {"type": "recommendation", "response": area_answer}

    kind = _classify(message)

    if kind == "stats":
        response = answer_stats_question(message)
        # When the question mentions a specific area, append the live area
        # intelligence data so the answer reflects real coverage numbers.
        if _LOCATION_PATTERN.search(text):
            area_ctx = area_metrics_summary()
            if area_ctx:
                response += "\n\n**Area Intelligence**\n" + area_ctx
        return {"type": "stats", "response": response}

    if kind == "recommendation":
        response = generate_recommendation(message)
        return {"type": "recommendation", "response": response}

    # troubleshooting — try guide first
    guide_result = search_guide(message)
    if guide_result:
        return {"type": "troubleshooting", "response": guide_result}

    # Guide had nothing — fall back to recommendation engine which can still help
    response = generate_recommendation(message)
    return {"type": "recommendation", "response": response}
