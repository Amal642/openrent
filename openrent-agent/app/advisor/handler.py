"""
Main entry point for the AI Advisor.
Classifies the question and routes to the appropriate handler.
"""

import re

from app.advisor.guide_parser import search_guide
from app.advisor.stats_service import answer_stats_question
from app.advisor.recommendation_engine import generate_recommendation


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


def handle_chat(message: str) -> dict:
    kind = _classify(message)

    if kind == "stats":
        response = answer_stats_question(message)
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
