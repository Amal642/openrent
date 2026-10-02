"""
Name extraction, property extraction, and landlord matching logic.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from openai import OpenAI

from app.config import settings
from app.db.connection import SessionLocal
from app.db.models import Account, Listing, SearchProfile
from app.utils.logger import logger

_client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=15.0)

# Auto-link confidence threshold (%)
AUTO_LINK_THRESHOLD = 65.0
UNIQUE_NAME_ONLY_CONFIDENCE = 90.0

# Greeting words to strip from extracted names
_STRIP_WORDS = {
    "hello", "hi", "hey", "good", "morning", "afternoon", "evening",
    "thanks", "thank", "you", "please", "there",
}

_TRAILING_NON_NAME_WORDS = {
    "the",
    "owner",
    "landlord",
    "property",
    "house",
    "flat",
    "apartment",
    "room",
}

_NAME_PATTERNS = [
    re.compile(r"\bi(?:'m| am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE),
    re.compile(r"\bmy name(?:'s| is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE),
    re.compile(r"\bthis is\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE),
    re.compile(r"\bit'?s\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE),
    re.compile(r"\bhi,?\s+i(?:'m| am)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE),
    re.compile(r"\bspeaking\s+with\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", re.IGNORECASE),
]


def _strip_greeting(text: str) -> str:
    words = text.split()
    result = [w for w in words if w.lower().strip(".,!?") not in _STRIP_WORDS]
    return " ".join(result)


def _clean_name_candidate(text: str) -> str:
    words = text.strip().split()
    while words and words[-1].lower().strip(".,!?") in _TRAILING_NON_NAME_WORDS:
        words.pop()
    return " ".join(words).strip(" ,.!?")


def extract_name_from_message(text: str) -> Optional[str]:
    """Try regex patterns first; fall back to LLM for messages >= 3 words."""
    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            name = _clean_name_candidate(match.group(1))
            if name:
                return name

    words = text.split()
    if len(words) < 3:
        return None

    # LLM fallback
    try:
        prompt = (
            "Extract only the person's name from this WhatsApp message. "
            "The sender is a landlord who texted our number. "
            "Reply with ONLY the name (e.g. 'John Smith') or 'NONE' if no name is present.\n\n"
            f"Message: {text}"
        )
        response = _client.chat.completions.create(
            model=settings.OPENAI_UTILITY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=30,
        )
        name = response.choices[0].message.content.strip()
        if name and name.upper() != "NONE" and len(name) <= 60:
            # Sanity: must look like a name (at least one capitalized word)
            if re.match(r"^[A-Za-z]", name):
                return name
    except Exception as exc:
        logger.warning(f"WHATSAPP_NAME_EXTRACT_LLM_FAILED error={exc}")

    return None


def extract_property_from_message(text: str) -> Optional[str]:
    """Use LLM to extract address/postcode/street from landlord message."""
    try:
        prompt = (
            "Extract the property address, postcode, or street name mentioned in this WhatsApp message. "
            "The sender is a UK landlord. "
            "Reply with ONLY the address/location (e.g. '12 Oak Street, London' or 'SW1A 1AA') "
            "or 'NONE' if no property is mentioned.\n\n"
            f"Message: {text}"
        )
        response = _client.chat.completions.create(
            model=settings.OPENAI_UTILITY_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=60,
        )
        result = response.choices[0].message.content.strip()
        if result and result.upper() != "NONE":
            return result
    except Exception as exc:
        logger.warning(f"WHATSAPP_PROPERTY_EXTRACT_LLM_FAILED error={exc}")

    return None


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio() * 100


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def _token_words(text: str | None) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", _norm(text))
        if len(token) >= 3
    ]


def _name_tokens_match(candidate: str | None, stored: str | None) -> bool:
    """Strict name-token match for safe name-only auto-linking."""
    candidate_tokens = _token_words(candidate)
    stored_tokens = _token_words(stored)
    if not candidate_tokens or not stored_tokens:
        return False
    if len(candidate_tokens) == 1:
        return stored_tokens[0] == candidate_tokens[0]
    return set(candidate_tokens).issubset(set(stored_tokens))


def _name_score(candidate: str | None, stored: str | None) -> float:
    if not candidate or not stored:
        return 0.0
    candidate_norm = _norm(candidate)
    stored_norm = _norm(stored)
    score = _similarity(candidate_norm, stored_norm)
    if candidate_norm and candidate_norm in stored_norm:
        score = max(score, 82.0)
    candidate_tokens = set(_token_words(candidate_norm))
    stored_tokens = set(_token_words(stored_norm))
    if candidate_tokens and candidate_tokens.issubset(stored_tokens):
        score = max(score, 78.0)
    return score


def _property_score(candidate: str | None, stored: str | None) -> float:
    if not candidate or not stored:
        return 0.0
    candidate_norm = _norm(candidate)
    stored_norm = _norm(stored)
    score = _similarity(candidate_norm, stored_norm)
    if candidate_norm and candidate_norm in stored_norm:
        score = max(score, 92.0)
    candidate_tokens = set(_token_words(candidate_norm))
    stored_tokens = set(_token_words(stored_norm))
    if candidate_tokens and candidate_tokens.issubset(stored_tokens):
        score = max(score, 88.0)

    full_postcode = re.search(r"\b([a-z]{1,2}\d[a-z\d]?)\s*(\d[a-z]{2})\b", candidate_norm)
    if full_postcode:
        full_code = (full_postcode.group(1) + full_postcode.group(2)).replace(" ", "")
        if full_code in stored_norm.replace(" ", ""):
            score = max(score, 96.0)
        outward = full_postcode.group(1)
    else:
        outward_match = re.search(r"\b([a-z]{1,2}\d[a-z\d]?)\b", candidate_norm)
        outward = outward_match.group(1) if outward_match else None

    # Stored listing addresses often only carry the outward code (e.g. "Canning
    # Town, E16" with no inward code), so a full-postcode candidate would never
    # match on `full_code` alone above — fall back to matching just the district.
    # A district holds thousands of addresses, so when the landlord also named a
    # street, the street decides: same street + district beats district-only,
    # and a DIFFERENT street in the same district must not tie with the right
    # one (2026-09-30: "Bedonwell Road DA17 5NZ" tied Wadeville Close, DA17 at
    # 90 vs 90.8, so a landlord who named the exact property stayed unmatched).
    if outward and re.search(rf"\b{re.escape(outward)}\b", stored_norm):
        # House numbers ("123a") are not street words.
        street = {t for t in _street_tokens(candidate_norm) if not any(ch.isdigit() for ch in t)}
        if not street:
            score = max(score, 90.0)
        elif not _conflicting_street_names(candidate_norm, stored_norm) and (
            street.issubset(stored_tokens) or _names_stored_street(candidate_norm, stored_norm)
        ):
            # Either every street word the landlord used is in our address, or
            # our listing's street appears in theirs: landlords add towns and
            # cross roads ("53 Headley Drive, Tadworth, Epsom Downs, KT18 5RP"
            # vs "Headley Drive, KT18" scored 70, like a different street).
            score = max(score, 96.0)
        else:
            # Different street in the same district, or the same name with a
            # different street type ("Farmers Close" vs "Farmers Place, SL9").
            score = min(max(score, 70.0), 70.0)
    elif outward and _OUTWARD_RE.search(stored_norm):
        # Both addresses carry a postcode district and they differ: a different
        # place, whatever the fuzzy text says ("Bedonwell Road DA17" vs "Well
        # Road, EN5" scored 59 on similarity alone and, via a recent handoff,
        # blocked the true match on 2026-09-30).
        score = min(score, 30.0)
    else:
        # No postcode to decide it: let the distinctive name words decide.
        # Sharing one ("Tothill House, Page Street" vs "Tothill House, SW1P") is
        # strong evidence; sharing none means a different place, however similar
        # the generic words ("... House") make the fuzzy score (2026-10-01:
        # "Horizon House, BR8" scored 86 via a recent handoff and blocked the
        # true match for a landlord who named her building).
        mine = _street_tokens(candidate_norm)
        theirs = _street_tokens(stored_norm)
        if mine and theirs:
            shared = (mine & theirs) - _conflicting_street_names(candidate_norm, stored_norm)
            if shared and mine <= theirs:
                score = max(score, 88.0)
            elif shared:
                score = max(score, 75.0)
            else:
                score = min(score, 30.0)
        elif not theirs and _names_stored_street(candidate_norm, stored_norm):
            # Our street is all common words ("Grove Place, AL9") but the
            # landlord wrote it out ("Grove Place, Welham Green").
            score = max(score, 80.0)

    return score


_OUTWARD_RE = re.compile(r"\b[a-z]{1,2}\d[a-z\d]?\b")


_GENERIC_ADDRESS_WORDS = {
    "road", "rd", "street", "st", "avenue", "ave", "close", "lane", "ln", "way",
    "drive", "dr", "court", "ct", "place", "pl", "gardens", "gdns", "crescent",
    "terrace", "grove", "square", "sq", "flat", "house", "the", "one", "property",
    "london", "uk", "and", "of",
    # Common in many unrelated addresses; must not count as "the same place".
    "park", "hill", "green", "north", "south", "east", "west", "upper", "lower",
    "new", "old", "great", "little", "high", "church", "station", "mill", "manor",
    "lodge", "view", "mews", "row", "walk", "rise", "hall", "gate", "common",
    "bridge", "wharf", "quay", "heights", "mansions", "villas", "cottages", "town",
    "city", "centre", "center", "studio", "apartment", "apartments", "maisonette",
    "room", "rooms", "bed", "beds", "bedroom", "bedrooms", "double", "single",
    "floor", "ground", "first", "top", "building", "block", "home", "your", "my",
    "about", "for", "this", "that", "with", "near",
}
_POSTCODE_PART_RE = re.compile(r"^(?:[a-z]{1,2}\d[a-z\d]?|\d[a-z]{2})$")


_STREET_TYPES = {
    "road", "rd", "street", "st", "avenue", "ave", "close", "lane", "ln", "way", "drive",
    "dr", "court", "ct", "place", "pl", "gardens", "gdns", "crescent", "terrace", "grove",
    "square", "sq", "park", "hill", "mews", "row", "walk", "rise", "green", "gate", "house",
    "lodge", "mansions", "villas", "cottages", "heights",
}


def _named_street_types(text: str) -> dict[str, set[str]]:
    words = re.findall(r"[a-z0-9]+", text)
    out: dict[str, set[str]] = {}
    for word, nxt in zip(words, words[1:]):
        if nxt in _STREET_TYPES and word not in _GENERIC_ADDRESS_WORDS:
            out.setdefault(word, set()).add(nxt)
    return out


def _conflicting_street_names(candidate_norm: str, stored_norm: str) -> set[str]:
    """Name words used with DIFFERENT street types on each side ("Elm Road" vs
    "Elm Park"), so sharing the word doesn't mean the same place."""
    mine, theirs = _named_street_types(candidate_norm), _named_street_types(stored_norm)
    return {w for w in mine.keys() & theirs.keys() if not (mine[w] & theirs[w])}


_UNIT_WORDS = {
    "flat", "studio", "apartment", "room", "rooms", "bed", "beds", "bedroom",
    "bedrooms", "double", "single", "the", "maisonette", "unit",
}


def _names_stored_street(candidate_norm: str, stored_norm: str) -> bool:
    """True when a street segment of our stored address ("clonmel road" in
    "studio flat, clonmel road, tw11") appears whole in the landlord's text."""
    candidate_text = " ".join(re.findall(r"[a-z0-9]+", candidate_norm.replace("'", "")))
    for segment in stored_norm.split(","):
        words = re.findall(r"[a-z0-9]+", segment.replace("'", ""))
        while words and (any(ch.isdigit() for ch in words[0]) or words[0] in _UNIT_WORDS):
            words = words[1:]  # "flat 3 montrose court" -> "montrose court"
        if len(words) < 2 or words[-1] not in _STREET_TYPES:
            continue
        if re.search(rf"\b{re.escape(' '.join(words))}\b", candidate_text):
            return True
    return False


def _street_tokens(text: str) -> set[str]:
    """Distinctive street/place words in an address hint (no postcode parts,
    numbers or generic words like "road"), e.g. "bedonwell road da17 5nz" ->
    {"bedonwell"}."""
    return {
        token
        for token in _token_words(text)
        if len(token) >= 3
        and not token.isdigit()
        and token not in _GENERIC_ADDRESS_WORDS
        and not _POSTCODE_PART_RE.match(token)
    }


def match_landlord_by_name(name: str) -> list[dict]:
    """
    Query listings table for landlord_name matches.
    Returns list of dicts with listing info and confidence score.
    """
    if not name:
        return []

    db = SessionLocal()
    try:
        # Fetch all listings that have a landlord_name
        # Only landlords we actually messaged can have our WhatsApp number.
        listings = (
            db.query(Listing)
            .filter(Listing.landlord_name.isnot(None), Listing.message_sent.is_(True))
            .all()
        )

        results = []
        for listing in listings:
            if not listing.landlord_name:
                continue
            sim = _name_score(name, listing.landlord_name)
            if sim >= 40:  # minimum to consider
                results.append({
                    "listing_id": listing.id,
                    "listing_listing_id": listing.listing_id,
                    "thread_id": listing.thread_id,
                    "landlord_name": listing.landlord_name,
                    "landlord_id": listing.landlord_id,
                    "property_address": listing.property_address,
                    "similarity": sim,
                })

        results.sort(key=lambda x: x["similarity"], reverse=True)
        return results
    finally:
        db.close()


def match_landlord_by_property(
    property_hint: str, name: Optional[str] = None
) -> tuple[Optional[dict], float]:
    """
    Fuzzy-match property_hint against listing addresses.
    Returns (best_match_dict, confidence) or (None, 0.0).
    """
    if not property_hint:
        return None, 0.0

    db = SessionLocal()
    try:
        listings = (
            db.query(Listing)
            .filter(Listing.property_address.isnot(None), Listing.message_sent.is_(True))
            .all()
        )

        best = None
        best_score = 0.0

        for listing in listings:
            if not listing.property_address:
                continue
            addr_sim = _property_score(property_hint, listing.property_address)

            # Combine name similarity if we have a name
            score = addr_sim
            if name and listing.landlord_name:
                name_sim = _name_score(name, listing.landlord_name)
                # Weight: 60% address, 40% name
                score = addr_sim * 0.6 + name_sim * 0.4
                if name_sim > 50 and addr_sim > 50:
                    score = min(95.0, score + 10)

            if score > best_score:
                best_score = score
                best = {
                    "listing_id": listing.id,
                    "listing_listing_id": listing.listing_id,
                    "thread_id": listing.thread_id,
                    "landlord_name": listing.landlord_name,
                    "landlord_id": listing.landlord_id,
                    "property_address": listing.property_address,
                    "similarity": score,
                }

        return best, best_score
    finally:
        db.close()


def get_all_match_candidates(
    name: Optional[str], property_hint: Optional[str]
) -> tuple[list[dict], float]:
    """
    Combine name and property matching.
    Returns (candidates_list, best_confidence).
    """
    candidates: list[dict] = []
    best_confidence = 0.0

    if name:
        name_matches = match_landlord_by_name(name)
        for m in name_matches:
            # Single name match = 70% confidence
            m["confidence"] = min(m["similarity"], 70.0)
            best_confidence = max(best_confidence, m["confidence"])
        candidates.extend(name_matches)

    if property_hint:
        prop_match, prop_score = match_landlord_by_property(property_hint, name)
        if prop_match:
            prop_match["confidence"] = prop_score
            best_confidence = max(best_confidence, prop_score)
            # Merge or add
            existing = next(
                (c for c in candidates if c["listing_id"] == prop_match["listing_id"]),
                None,
            )
            if existing:
                existing["confidence"] = max(existing["confidence"], prop_score)
            else:
                candidates.append(prop_match)

    # Re-sort by confidence
    candidates.sort(key=lambda x: x["confidence"], reverse=True)
    return candidates, best_confidence


# A landlord who pastes the OpenRent listing link has told us exactly which
# property it is (2026-10-02: "Aziz Property Group" sent the Chestnut Grove CR4
# link and still stayed UNMATCHED on a 3.6-point gap). Link IDs are stored in
# the contact's property_hints with this prefix so they persist across messages.
LISTING_HINT_PREFIX = "openrent-listing:"
_LISTING_LINK_RE = re.compile(r"openrent\.co\.uk/\S*?(\d{6,9})(?=$|[/?#\s)\]>.,])", re.I)
LISTING_LINK_CONFIDENCE = 99.0
# When the landlord names one of our personas ("your partner Claire contacted
# us", "is this Nicola?"), candidates on that persona's account get a modest
# boost; it can tip a near-tie but never outranks a listing link.
PERSONA_BOOST = 8.0
PERSONA_BOOST_CAP = 97.0
# Minimum address score for a handoff intent's property evidence to count.
HANDOFF_MIN_PROPERTY_SCORE = 75.0


def extract_listing_ids(text: str | None) -> list[str]:
    """OpenRent listing IDs from any openrent.co.uk links in the text."""
    return list(dict.fromkeys(_LISTING_LINK_RE.findall(text or "")))


def mentioned_persona_names(texts: list[str]) -> list[str]:
    """The ONE persona first name a landlord used for us (partner X, is this X,
    hi X, X contacted us...). Empty when none or more than one, so a landlord
    who happens to share a persona's name, or a vague message, adds nothing."""
    db = SessionLocal()
    try:
        personas = {
            (name or "").strip()
            for (name,) in db.query(Account.persona_name).filter(
                Account.active.is_(True), Account.deleted_at.is_(None)
            )
            if name and len(name.strip()) >= 3
        }
    finally:
        db.close()
    found = set()
    blob = "\n".join(t for t in texts if t)
    for persona in personas:
        n = re.escape(persona)
        patterns = (
            rf"\b(?:partner|wife|husband|other half|girlfriend|boyfriend)\s+(?:is\s+)?{n}\b",
            rf"\b(?:is this|is that|are you|speak(?:ing)? (?:to|with)|hi|hello|hey|dear|morning)\s+{n}\b",
            rf"\b{n}(?:'s|’s)?\s+(?:contacted|messaged|enquired|gave|sent|asked|from open\s?rent)\b",
        )
        if any(re.search(p, blob, re.I) for p in patterns):
            found.add(persona)
    return sorted(found) if len(found) == 1 else []


def match_by_evidence(
    names: list[str] | None,
    property_hints: list[str] | None,
    line_number: str | None = None,
    persona_names: list[str] | None = None,
) -> tuple[list[dict], float]:
    """Score listings against accumulated WhatsApp name and property evidence.

    line_number is OUR number the landlord wrote to (any format); when given,
    handoff priors for a different give-out number are ignored.
    persona_names: our persona the landlord named (see mentioned_persona_names).
    """
    names = [n.strip() for n in (names or []) if n and n.strip()]
    property_hints = [p.strip() for p in (property_hints or []) if p and p.strip()]
    link_ids = list(dict.fromkeys(
        h[len(LISTING_HINT_PREFIX):] for h in property_hints if h.startswith(LISTING_HINT_PREFIX)
    ))
    property_hints = [h for h in property_hints if not h.startswith(LISTING_HINT_PREFIX)]

    db = SessionLocal()
    try:
        # Only listings we messaged: a landlord can only have our WhatsApp number
        # if we contacted them. Scoring never-contacted listings produced
        # "matches" with no conversation (lead marked acquired, never exported).
        listings = db.query(Listing).filter(Listing.message_sent.is_(True)).all()
        candidates = []
        strict_name_only_listing_ids: set[int] = set()

        for listing in listings:
            best_name = (None, 0.0)
            for name in names:
                score = _name_score(name, listing.landlord_name)
                if score > best_name[1]:
                    best_name = (name, score)

            best_property = (None, 0.0)
            for hint in property_hints:
                score = _property_score(hint, listing.property_address)
                if score > best_property[1]:
                    best_property = (hint, score)

            name_score = best_name[1]
            property_score = best_property[1]

            if name_score and property_score:
                confidence = property_score * 0.6 + name_score * 0.4
                reason = "name+property"
                if name_score >= 60 and property_score >= 75:
                    confidence = min(98.0, confidence + 8)
            elif property_score:
                confidence = property_score
                reason = "property"
            elif name_score:
                # Name-only is useful but less safe because names are not unique.
                confidence = min(name_score, 72.0)
                reason = "name"
                if _name_tokens_match(best_name[0], listing.landlord_name):
                    strict_name_only_listing_ids.add(listing.id)
            else:
                continue

            if confidence < 40:
                continue

            candidates.append({
                "listing_id": listing.id,
                "listing_listing_id": listing.listing_id,
                "thread_id": listing.thread_id,
                "landlord_name": listing.landlord_name,
                "landlord_id": listing.landlord_id,
                "property_address": listing.property_address,
                "confidence": confidence,
                "name_score": name_score,
                "property_score": property_score,
                "matched_name": best_name[0],
                "matched_property_hint": best_property[0],
                "reason": reason,
            })

        if names and not property_hints and len(strict_name_only_listing_ids) == 1:
            unique_listing_id = next(iter(strict_name_only_listing_ids))
            for candidate in candidates:
                if candidate["listing_id"] == unique_listing_id:
                    candidate["confidence"] = max(
                        candidate["confidence"],
                        UNIQUE_NAME_ONLY_CONFIDENCE,
                    )
                    candidate["reason"] = "unique_name"
                    break

        # Handoff-intent prior: boost/add candidates for threads we recently gave
        # the WhatsApp number to (a landlord just handed the number almost
        # certainly belongs to that thread). Feeds well-founded candidates to the
        # caller's threshold+gap logic WITHOUT changing it; no intents -> unchanged.
        _apply_handoff_prior(db, candidates, names, property_hints, line_number)
        _apply_persona_boost(db, candidates, persona_names)
        _apply_listing_links(db, candidates, link_ids)

        candidates.sort(key=lambda x: x["confidence"], reverse=True)
        return candidates, candidates[0]["confidence"] if candidates else 0.0
    finally:
        db.close()


def _apply_persona_boost(db, candidates, persona_names):
    """Boost candidates whose listing belongs to the persona the landlord named."""
    if not persona_names or not candidates:
        return
    wanted = {p.casefold() for p in persona_names}
    ids = [c["listing_id"] for c in candidates if c.get("listing_id")]
    persona_of = dict(
        db.query(Listing.id, Account.persona_name)
        .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
        .join(Account, SearchProfile.account_id == Account.id)
        .filter(Listing.id.in_(ids))
        .all()
    )
    for candidate in candidates:
        persona = (persona_of.get(candidate.get("listing_id")) or "").casefold()
        if persona and persona in wanted and candidate["confidence"] < PERSONA_BOOST_CAP:
            candidate["confidence"] = min(PERSONA_BOOST_CAP, candidate["confidence"] + PERSONA_BOOST)
            candidate["reason"] = f"{candidate.get('reason') or ''}+persona"


def _apply_listing_links(db, candidates, link_ids):
    """A pasted listing link for a listing we messaged is a certain match: put
    it at LISTING_LINK_CONFIDENCE and, when exactly one such listing is linked,
    hold every other candidate below the auto-match gap."""
    linked = []
    for listing_ref in link_ids:
        listing = (
            db.query(Listing)
            .filter(Listing.listing_id == listing_ref, Listing.message_sent.is_(True))
            .first()
        )
        if listing:
            linked.append(listing)
    if not linked:
        return
    by_listing = {c["listing_id"]: c for c in candidates}
    for listing in linked:
        candidate = by_listing.get(listing.id)
        if candidate is None:
            candidate = {
                "listing_id": listing.id,
                "listing_listing_id": listing.listing_id,
                "thread_id": listing.thread_id,
                "landlord_name": listing.landlord_name,
                "landlord_id": listing.landlord_id,
                "property_address": listing.property_address,
                "name_score": 0.0,
                "property_score": 0.0,
                "matched_name": None,
                "matched_property_hint": f"{LISTING_HINT_PREFIX}{listing.listing_id}",
            }
            candidates.append(candidate)
            by_listing[listing.id] = candidate
        candidate["confidence"] = LISTING_LINK_CONFIDENCE
        candidate["reason"] = "listing_link"
    if len({listing.id for listing in linked}) == 1:
        linked_id = linked[0].id
        for candidate in candidates:
            if candidate["listing_id"] != linked_id:
                candidate["confidence"] = min(candidate["confidence"], LISTING_LINK_CONFIDENCE - 9)


_COMPANY_NAME_WORDS = {
    "property", "properties", "group", "holdings", "holding", "ltd", "limited",
    "lettings", "letting", "estates", "estate", "homes", "management",
    "investments", "investment", "services", "capital", "living", "residential",
    "rentals", "rental", "real", "uk",
}


def _handoff_name_score(name: str | None, landlord_name: str | None) -> float:
    """Name score with company words removed, so "Aziz Property Group" doesn't
    look like "Gemini Property Holdings U." (56.5, enough to lift that handoff
    to 80 on 2026-10-02). Personal names and nicknames score as before."""
    def strip(text):
        return " ".join(
            w for w in re.findall(r"[A-Za-z0-9'.-]+", text or "")
            if w.lower().strip(".") not in _COMPANY_NAME_WORDS
        )
    a, b = strip(name), strip(landlord_name)
    if a == (name or "").strip() and b == (landlord_name or "").strip():
        return _name_score(name, landlord_name)
    return _name_score(a, b) if a and b else 0.0


def _apply_handoff_prior(db, candidates, names, property_hints, line_number=None):
    """Boost/add candidates from recent, unconsumed WhatsApp handoff intents.

    With several give-out numbers, a landlord can only be writing in response
    to a handoff of the number they wrote to: intents that recorded a different
    shared_number are skipped. Legacy intents (no shared_number) or an unknown
    line keep the old all-intents behaviour.

    A landlord we handed the number to in the last 7 days is a strong prior for
    that thread, so a name-only match here outweighs the generic name-only cap
    (72). Confidences stay below certainty so the caller's threshold+gap logic
    still resolves ambiguity (two similar recent handoffs -> stays UNMATCHED ->
    asks "which property?"). Fail-safe: any error degrades to normal matching.
    """
    from datetime import datetime, timedelta
    from app.db.models import WhatsAppHandoffIntent
    try:
        cutoff = datetime.utcnow() - timedelta(days=7)
        intents = (
            db.query(WhatsAppHandoffIntent)
            .filter(
                WhatsAppHandoffIntent.created_at >= cutoff,
                WhatsAppHandoffIntent.matched_contact_id.is_(None),
            )
            .all()
        )
    except Exception as exc:
        logger.warning(f"WHATSAPP_HANDOFF_PRIOR_SKIPPED error={exc}")
        return
    if not intents:
        return
    from app.whatsapp.lines import national_digits

    line_digits = national_digits(line_number)
    by_listing = {c["listing_id"]: c for c in candidates}
    for intent in intents:
        shared = national_digits(getattr(intent, "shared_number", None))
        if line_digits and shared and shared != line_digits:
            continue
        nm = max((_handoff_name_score(n, intent.landlord_name) for n in names), default=0.0)
        pm = max((_property_score(h, intent.property_address) for h in property_hints), default=0.0)
        # Property evidence only counts here at street level (>= 75): a
        # different street in the same district scores 70 and must not lift a
        # handoff over the listing whose street the landlord actually named
        # (2026-10-02: London Road CR4 at 88.4 beat an exact Chestnut Grove CR4).
        strong_pm = pm >= HANDOFF_MIN_PROPERTY_SCORE
        if nm < 50 and not strong_pm:
            continue
        if strong_pm and nm >= 50:
            conf = min(97.0, 82.0 + pm * 0.12)
        elif strong_pm:
            conf = min(95.0, 80.0 + pm * 0.12)
        else:
            conf = min(88.0, 70.0 + nm * 0.18)
        existing = by_listing.get(intent.listing_id)
        if existing:
            if conf > existing["confidence"]:
                existing["confidence"] = conf
                existing["reason"] = "handoff"
        else:
            cand = {
                "listing_id": intent.listing_id,
                "listing_listing_id": None,
                "thread_id": intent.thread_id,
                "landlord_name": intent.landlord_name,
                "landlord_id": None,
                "property_address": intent.property_address,
                "confidence": conf,
                "name_score": nm,
                "property_score": pm,
                "matched_name": None,
                "matched_property_hint": None,
                "reason": "handoff",
            }
            candidates.append(cand)
            by_listing[intent.listing_id] = cand
