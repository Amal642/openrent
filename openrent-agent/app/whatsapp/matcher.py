"""
Name extraction, property extraction, and landlord matching logic.
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from openai import OpenAI
from sqlalchemy import or_

from app.config import settings
from app.db.connection import SessionLocal
from app.db.models import Account, Conversation, Listing, SearchProfile, WhatsAppContact
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
    *,
    contact_phone: str | None = None,
    inbound_texts: list[str] | None = None,
    contact_id: int | None = None,
    as_of=None,
) -> tuple[list[dict], float]:
    """Score listings against accumulated WhatsApp name and property evidence.

    line_number is OUR number the landlord wrote to (any format); when given,
    handoff priors for a different give-out number are ignored.
    persona_names: our persona the landlord named (see mentioned_persona_names).
    contact_phone / inbound_texts / contact_id: the contact's own number and
    messages, for the given-number evidence (see _apply_given_number_evidence).
    as_of: the moment to judge from (default now); the replay harness passes the
    contact's first message time so nothing learned later leaks in.
    """
    names = [n.strip() for n in (names or []) if n and n.strip()]
    property_hints = [p.strip() for p in (property_hints or []) if p and p.strip()]
    link_ids = list(dict.fromkeys(
        h[len(LISTING_HINT_PREFIX):] for h in property_hints if h.startswith(LISTING_HINT_PREFIX)
    ))
    property_hints = [h for h in property_hints if not h.startswith(LISTING_HINT_PREFIX)]

    db = SessionLocal()
    try:
        if inbound_texts:
            # "Hi Jessica" made the extractor list our persona as the landlord's
            # name; most of the replay's wrong links (Alex, Claire, Isabelle,
            # Jessica, Olivia, Victoria) scored that name against landlords.
            greeted = _greeted_persona_names(db, inbound_texts)
            names = [n for n in names if (n.split() or [""])[0].casefold() not in greeted]
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
        # Given-number evidence first, then the persona boost, the same order
        # the handoff prior and boost ran in (the boost reaches these threads).
        pool_threads = _apply_given_number_evidence(
            db, candidates, names, property_hints, inbound_texts or [], line_number,
            as_of=as_of, contact_id=contact_id, boosted_personas=persona_names,
        )
        _apply_persona_boost(db, candidates, persona_names)
        _apply_phone_match(db, candidates, contact_phone, as_of=as_of, pool_threads=pool_threads)
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


# ---------------------------------------------------------------------------
# Given-number evidence (2026-10-08).
#
# A landlord can only have our WhatsApp number if one of our threads gave it to
# them, so the threads where we handed it over in the days before they wrote
# are the real candidate pool. Within that pool the decisive evidence was being
# ignored, which left real landlords SAVED_UNMATCHED (~1/day; 9 linked by hand
# on 2026-10-08):
#   * the address they give is often in the OpenRent chat ("Church Street,
#     London, E16 2NB") while our stored listing address is only an area
#     ("Church St, E16"), so the chat is compared too;
#   * they name our persona or partner ("Harriet shared your number", "Hi
#     George"), which narrows the pool to that account;
#   * the landlord's number may already be on the thread (certain match);
#   * a landlord who names a different district/street is ruled out;
#   * the persona they name only breaks ties (timing was tried and dropped:
#     it moved competitors past the old margins in the 2026-10-08 replay).
# ---------------------------------------------------------------------------
# 97% of linked landlords write within 7 days of the give-out (222 contacts,
# 2026-10-08); a longer window only adds competing threads.
GIVEN_NUMBER_WINDOW_DAYS = 7
PHONE_MATCH_CONFIDENCE = 99.0
GIVEN_NUMBER_MAX_CONFIDENCE = 97.0

# "<persona> shared/passed on/gave your number". Not "<name> from OpenRent":
# that is how landlords introduce THEMSELVES ("Laura from OpenRent"), and the
# 2026-10-08 replay showed it narrowing contacts to the wrong account.
_REFERRAL_VERBS = (
    r"(?:shared|passed(?:\s+on)?|provided|gave|given|forwarded|sent)\s+(?:me\s+|us\s+)?"
    r"(?:your|this|the|his|her|their)\s+(?:whats\s*app\s+)?(?:number|contact|details|whats\s*app)"
)


REFERRAL_STRONG, REFERRAL_WEAK = 2, 1


def mentioned_account_ids(db, texts: list[str], exclude_names=None) -> set[int]:
    """Accounts whose persona OR partner name the landlord used for us."""
    return set(mentioned_account_strength(db, texts, exclude_names))


def mentioned_account_strength(db, texts: list[str], exclude_names=None) -> dict[int, int]:
    """{account_id: strength} for persona OR partner names the landlord used for
    us. REFERRAL_STRONG for an explicit referral ("your partner Claire",
    "Harriet shared your number"), REFERRAL_WEAK for a greeting ("Hi George").
    Empty when none, or when names of more than two different people appear
    (a vague or name-heavy message decides nothing)."""
    blob = "\n".join(t for t in texts if t)
    if not blob.strip():
        return {}
    rows = (
        db.query(Account.id, Account.persona_name, Account.persona_partner_name)
        .filter(Account.deleted_at.is_(None))
        .all()
    )
    by_name: dict[str, set[int]] = {}
    for acc_id, persona, partner in rows:
        for nm in (persona, partner):
            nm = (nm or "").strip()
            if len(nm) >= 3:
                by_name.setdefault(nm.casefold(), set()).add(acc_id)
    # A landlord called Olivia writing about her own flat is not naming our Olivia.
    own = {w.casefold() for n in (exclude_names or []) for w in re.findall(r"[A-Za-z]{3,}", n or "")}
    found: dict[str, tuple[set[int], int]] = {}
    for key, ids in by_name.items():
        if key in own:
            continue
        n = re.escape(key)
        strong = (
            rf"\b(?:partner|wife|husband|other half|girlfriend|boyfriend|fianc[eé]e?)\s+(?:is\s+)?{n}\b",
            rf"\b{n}\s+(?:has\s+|had\s+|just\s+)?{_REFERRAL_VERBS}\b",
            rf"\b{n}(?:'s|\u2019s)\s+(?:partner|husband|wife)\b",
        )
        weak = (
            rf"\b(?:is this|is that|are you|speak(?:ing)? (?:to|with)|hi|hello|hey|hiya|dear|morning|afternoon|evening)\s+{n}\b",
        )
        if any(re.search(p, blob, re.I) for p in strong):
            found[key] = (ids, REFERRAL_STRONG)
        elif any(re.search(p, blob, re.I) for p in weak):
            found[key] = (ids, REFERRAL_WEAK)
    if not found or len(found) > 2:
        return {}
    out: dict[int, int] = {}
    for ids, strength in found.values():
        for acc in ids:
            out[acc] = max(out.get(acc, 0), strength)
    return out


def _phone_digits(phone: str | None) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("44"):
        digits = "0" + digits[2:]
    return digits


def _apply_phone_match(db, candidates, contact_phone, *, as_of=None, pool_threads=None):
    """The landlord's WhatsApp number is already the number we captured on one
    OpenRent thread (before this contact wrote): that thread, for certain."""
    from datetime import datetime

    digits = _phone_digits(contact_phone)
    if len(digits) < 10:
        return
    now = as_of or datetime.utcnow()
    # Stored captures are mostly "07…", some "+447…" / "447…".
    forms = {digits, "+44" + digits[1:], "44" + digits[1:]}
    rows = (
        db.query(Conversation, Listing)
        .join(Listing, Conversation.listing_id == Listing.id)
        .filter(Conversation.extracted_phone.in_(list(forms)))
        .filter(or_(Conversation.phone_found_at.is_(None), Conversation.phone_found_at < now))
        .all()
    )
    hits = [(c, l) for c, l in rows if _phone_digits(c.extracted_phone) == digits]
    if pool_threads is not None:
        # Same landlord, several of our threads: only the one we gave the
        # number to is the one they are writing about.
        hits = [(c, l) for c, l in hits if c.thread_id in pool_threads]
    if len(hits) != 1:
        return
    conversation, listing = hits[0]
    by_listing = {c["listing_id"]: c for c in candidates}
    cand = by_listing.get(listing.id)
    if cand is None:
        cand = _candidate_for(listing, conversation.thread_id)
        candidates.append(cand)
    cand["confidence"] = PHONE_MATCH_CONFIDENCE
    cand["reason"] = "phone"
    for other in candidates:
        if other is not cand:
            other["confidence"] = min(other["confidence"], PHONE_MATCH_CONFIDENCE - 9)


def _candidate_for(listing, thread_id):
    return {
        "listing_id": listing.id,
        "listing_listing_id": listing.listing_id,
        "thread_id": thread_id or listing.thread_id,
        "landlord_name": listing.landlord_name,
        "landlord_id": listing.landlord_id,
        "property_address": listing.property_address,
        "confidence": 0.0,
        "name_score": 0.0,
        "property_score": 0.0,
        "matched_name": None,
        "matched_property_hint": None,
        "reason": "",
    }


def _given_number_pool(db, as_of, line_number, contact_id=None):
    """(conversation, listing, account, given_at) for every thread where we
    handed out a WhatsApp number in the window before as_of. Respects the line
    when the handoff recorded which number it gave."""
    from datetime import timedelta
    from app.db.models import WhatsAppHandoffIntent
    from app.whatsapp.lines import national_digits

    start = as_of - timedelta(days=GIVEN_NUMBER_WINDOW_DAYS)
    end = as_of + timedelta(hours=1)
    line_digits = national_digits(line_number)

    given: dict[str, object] = {}
    with_intent: set[str] = set()
    snapshot_names: dict[str, set[str]] = {}
    wrong_line: set[str] = set()
    taken = {
        thread_id
        for (thread_id,) in db.query(WhatsAppContact.thread_id).filter(
            WhatsAppContact.thread_id.isnot(None),
            WhatsAppContact.created_at < as_of,
            WhatsAppContact.id != (contact_id or -1),
        )
    }
    for intent in (
        db.query(WhatsAppHandoffIntent)
        .filter(WhatsAppHandoffIntent.created_at >= start, WhatsAppHandoffIntent.created_at <= end)
        .all()
    ):
        if intent.matched_contact_id and intent.matched_contact_id != contact_id:
            taken.add(intent.thread_id)  # that landlord already reached us
            continue
        shared = national_digits(getattr(intent, "shared_number", None))
        if line_digits and shared and shared != line_digits:
            wrong_line.add(intent.thread_id)
            continue
        if intent.thread_id:
            prev = given.get(intent.thread_id)
            given[intent.thread_id] = max(prev, intent.created_at) if prev else intent.created_at
            with_intent.add(intent.thread_id)
            if intent.landlord_name:
                snapshot_names.setdefault(intent.thread_id, set()).add(intent.landlord_name)
    for thread_id, shared_at in (
        db.query(Conversation.thread_id, Conversation.our_number_shared_at)
        .filter(Conversation.our_number_shared_at >= start, Conversation.our_number_shared_at <= end)
        .all()
    ):
        if thread_id in wrong_line or thread_id in given:
            continue
        given[thread_id] = shared_at
    for thread_id in taken:
        given.pop(thread_id, None)
    if not given:
        return []
    rows = (
        db.query(Conversation, Listing, Account)
        .join(Listing, Conversation.listing_id == Listing.id)
        .outerjoin(SearchProfile, Listing.search_profile_id == SearchProfile.id)
        .outerjoin(Account, SearchProfile.account_id == Account.id)
        .filter(Conversation.thread_id.in_(list(given)))
        .all()
    )
    return [
        (c, l, a, given[c.thread_id], c.thread_id in with_intent, snapshot_names.get(c.thread_id, set()))
        for c, l, a in rows
    ]


def _chat_address_score(hint: str, chat: str) -> float:
    """Address evidence from the landlord's own OpenRent messages. A long chat
    "contains" most short hints word by word, so only a full postcode or every
    distinctive street/building word of the hint counts."""
    if not hint or not chat:
        return 0.0
    hint_norm, chat_norm = _norm(hint), _norm(chat)
    postcode = re.search(r"\b([a-z]{1,2}\d[a-z\d]?)\s*(\d[a-z]{2})\b", hint_norm)
    if postcode and (postcode.group(1) + postcode.group(2)) in chat_norm.replace(" ", ""):
        return 96.0
    # The whole "<name> <road/building word>" phrase must appear ("austin
    # house", "kent road"): one loose word like "austin" matched other chats.
    chat_text = " ".join(re.findall(r"[a-z0-9]+", chat_norm))
    words = re.findall(r"[a-z0-9]+", hint_norm)
    for i in range(1, len(words)):
        def _name_word(w):
            return w not in _GENERIC_ADDRESS_WORDS and not any(ch.isdigit() for ch in w)

        if words[i] in _STREET_TYPES and _name_word(words[i - 1]):
            start = i - 1
            while start > 0 and _name_word(words[start - 1]):
                start -= 1
            phrase = " ".join(words[start:i + 1])
            if re.search(rf"\b{re.escape(phrase)}\b", chat_text):
                return 88.0
    return 0.0


# Roads, as opposed to buildings ("Austin House", "River Heights") and bare
# places ("Sydenham"). A building sits ON a road, so "Christopher Bell Tower"
# vs "Pancras Way" is the same place; only two different roads contradict.
_THOROUGHFARES = {
    "road", "rd", "street", "st", "avenue", "ave", "lane", "ln", "way", "drive", "dr",
    "close", "crescent", "place", "pl", "grove", "terrace", "square", "sq", "walk",
    "rise", "mews", "row", "gardens", "gdns", "hill", "gate", "green", "park",
}


def _names_a_road(text: str | None) -> bool:
    for segment in _norm(text).split(","):
        words = re.findall(r"[a-z0-9]+", segment)
        for word, nxt in zip(words, words[1:]):
            # "London Road" is a road; only a number or a unit word ("flat
            # road") is not a road name.
            if nxt in _THOROUGHFARES and word not in _UNIT_WORDS and not any(ch.isdigit() for ch in word):
                return True
    return False


def _names_a_street(address: str | None) -> bool:
    """True when a stored address names a street or building ("London Road,
    CR4", "Proton Tower, E14"), not just an area ("Chiswick, W4", "St Johns
    Wood, NW8": the "St" there is Saint, so only a segment that ENDS in a
    street word counts)."""
    for segment in _norm(address).split(","):
        words = re.findall(r"[a-z0-9]+", segment)
        if len(words) >= 2 and (words[-1] in _STREET_TYPES or words[-1] in {"tower", "building", "wharf"}):
            return True
    return False


def _address_rules_out(hints, stored_address, chat: str = "") -> bool:
    """The landlord's own address says this is NOT the listing: a different
    postcode district, or our listing names a street and theirs is a
    different one (and the street is not in their OpenRent chat either).
    Vague hints ("the flat") and area-only listings rule nothing out."""
    if not stored_address:
        return False
    stored_norm = _norm(stored_address)
    stored_districts = set(_OUTWARD_RE.findall(stored_norm))
    ruled_out = False
    for hint in hints or []:
        if not _hint_is_specific(hint):
            continue
        if (
            _property_score(hint, stored_address) >= 75
            or (chat and _chat_address_score(hint, chat) >= 88)
        ):
            return False  # some hint supports it
        hint_districts = set(_OUTWARD_RE.findall(_norm(hint)))
        if hint_districts and stored_districts and not (hint_districts & stored_districts):
            ruled_out = True
        elif _names_a_road(hint) and _names_a_road(stored_address):
            ruled_out = True
    return ruled_out


def _landlord_chat_text(db, conversation_id, as_of) -> str:
    from app.db.models import Message

    rows = (
        db.query(Message.content)
        .filter(
            Message.conversation_id == conversation_id,
            Message.direction == "inbound",
            Message.created_at < as_of,
        )
        .all()
    )
    return " ".join(content for (content,) in rows if content)


def _apply_given_number_evidence(
    db, candidates, names, property_hints, inbound_texts, line_number, *, as_of=None, contact_id=None,
    boosted_personas=None,
):
    """Score the threads that gave this landlord our number. See the block
    comment above. Only adds or raises candidates; a thread the landlord's own
    address rules out is never lifted. Returns the pool's thread ids (None when
    the pool could not be read)."""
    from datetime import datetime

    now = as_of or datetime.utcnow()
    try:
        pool = _given_number_pool(db, now, line_number, contact_id)
    except Exception as exc:  # evidence is optional; never break matching
        logger.warning(f"WHATSAPP_GIVEN_NUMBER_POOL_FAILED error={exc}")
        return None
    if not pool:
        return set()
    mentioned = mentioned_account_strength(db, inbound_texts, exclude_names=names)
    boosted = {p.casefold() for p in (boosted_personas or [])}
    # Greeted persona names were already removed in match_by_evidence.
    landlord_names = names
    by_listing = {c["listing_id"]: c for c in candidates}
    for conversation, listing, account, given_at, has_intent, snapshots in pool:
        strength = mentioned.get(account.id, 0) if account is not None else 0
        # _apply_persona_boost already adds its +8 for this persona: counting it
        # twice put several threads on the 97 cap together (2026-10-08 replay).
        if account is not None and (account.persona_name or "").casefold() in boosted:
            strength = 0
        persona_hit = strength > 0
        address = 0.0
        if property_hints:
            chat = _landlord_chat_text(db, conversation.id, now)
            address = max(
                max(_property_score(h, listing.property_address), _chat_address_score(h, chat))
                for h in property_hints
            )
            if _address_rules_out(property_hints, listing.property_address, chat):
                continue
        # The landlord name as it was when we gave the number (the handoff
        # snapshot the old prior scored) or as the listing shows it now.
        stored_names = {listing.landlord_name, *snapshots} - {None}
        name = max(
            (_handoff_name_score(n, stored) for n in landlord_names for stored in stored_names),
            default=0.0,
        )
        strong_address = address >= 75
        # Real evidence is required: the address or the landlord's name. The
        # persona only breaks ties between threads that have some.
        # Threads with a recorded handoff keep the old prior's bar (name >= 50);
        # the ones this widened pool adds (number given, no handoff recorded)
        # need a solid name, so they don't bring in coin-flip competitors.
        if not strong_address:
            if has_intent and name < 50:
                continue
            # They named a specific address and it is not this listing's: a
            # borderline name ("Lauren" ~ "Darren L." at 53, about "Malden Rd"
            # vs Goosander Court NW9) must not carry it.
            if address < 70 and any(_hint_is_specific(h) for h in property_hints) and name < 70:
                continue
            if not has_intent and not (name >= 90 or _same_first_name(landlord_names, listing.landlord_name)):
                continue
        # Same continuous scale as the handoff prior this replaces, so every
        # case it already decided keeps its score (the 2026-10-08 replay showed
        # bucketed scores flattening name quality into near-ties). What is new
        # rides on top: the street/postcode found in their OpenRent chat counts
        # as a strong address, an area-only listing in their district adds a
        # little, and the persona the landlord names is a tie-breaker.
        if strong_address and name >= 50:
            conf = 82.0 + address * 0.12
        elif strong_address:
            conf = 80.0 + address * 0.12
        else:
            conf = min(88.0, 70.0 + name * 0.18)
            if address >= 70 and not _names_a_street(listing.property_address):
                conf += 3.0
        if name >= 50:
            conf += _initial_agreement(landlord_names, listing.landlord_name)
        # "Harriet shared your number" names who gave it: enough to separate
        # two otherwise equal threads. A bare "Hi George" only nudges.
        conf += 6.0 if strength >= REFERRAL_STRONG else 3.0 if persona_hit else 0.0
        conf = min(GIVEN_NUMBER_MAX_CONFIDENCE, conf)
        cand = by_listing.get(listing.id)
        if cand is None:
            cand = _candidate_for(listing, conversation.thread_id)
            cand["property_score"], cand["name_score"] = address, name
            candidates.append(cand)
            by_listing[listing.id] = cand
        if conf > cand["confidence"]:
            cand["confidence"] = conf
            cand["reason"] = "given_number" + ("+persona" if persona_hit else "")
    return {row[0].thread_id for row in pool}


def _persona_first_names(db) -> set[str]:
    names = set()
    for persona, partner in db.query(Account.persona_name, Account.persona_partner_name):
        for n in (persona, partner):
            if n and n.strip():
                names.add(n.strip().split()[0].casefold())
    return names


_GREETING_RE = re.compile(
    r"\b(?:hi|hello|hey|hiya|dear|morning|afternoon|evening|thanks|thank you|cheers)[,!\s]+([a-z]{3,})\b", re.I
)
_SELF_INTRO_RE = re.compile(
    r"\b(?:this is|it'?s|it\u2019s|i'?m|i am|my name is|name'?s|from)\s+([a-z]{3,})\b", re.I
)


def _greeted_persona_names(db, texts) -> set[str]:
    """Persona/partner first names the landlord addressed us by ("Hi Claire"),
    minus any they also used for themselves ("It's Laura")."""
    ours = _persona_first_names(db)
    blob = "\n".join(t for t in texts or [] if t)
    greeted = {m.casefold() for m in _GREETING_RE.findall(blob)} & ours
    themselves = {m.casefold() for m in _SELF_INTRO_RE.findall(blob)}
    return greeted - themselves


def _same_first_name(names, landlord_name) -> bool:
    """Exact first-name match ("Gill" / "Gill S."), not a fuzzy one ("Gill" /
    "Gillian S." scored 82 and tied the right thread)."""
    stored = re.findall(r"[A-Za-z]+", landlord_name or "")
    if not stored:
        return False
    first = stored[0].casefold()
    return any((re.findall(r"[A-Za-z]+", n or "") or [""])[0].casefold() == first for n in names or [])


def _initial_agreement(names, landlord_name) -> float:
    """OpenRent shows landlords as "First L." When the WhatsApp name has a
    surname, its initial agreeing ("Allan Adams" / "Allan A.") separates
    near-name ties (Allan vs Alan L. vs Gillian S.); disagreeing counts against."""
    stored = re.findall(r"[A-Za-z]+", landlord_name or "")
    if len(stored) < 2 or len(stored[-1]) != 1:
        return 0.0
    initial = stored[-1].casefold()
    best = 0.0
    for n in names or []:
        parts = re.findall(r"[A-Za-z]+", n or "")
        if len(parts) < 2 or parts[0].casefold() != stored[0].casefold():
            continue
        best = max(best, 3.0) if parts[-1][0].casefold() == initial else min(best, -5.0) if best <= 0 else best
    return best


def _hint_is_specific(hint: str) -> bool:
    """A hint that names a road, a building, or a postcode district can rule a
    listing out. "The flat", and area or town names ("Royal Victoria",
    "Sydenham", "Luton"), cannot: our listing addresses are often an area or a
    building, so a bare place name proves nothing against them."""
    norm = _norm(hint)
    if _OUTWARD_RE.search(norm):
        return True
    words = re.findall(r"[a-z0-9]+", norm)
    return any(
        nxt in _STREET_TYPES and word not in _UNIT_WORDS and not any(ch.isdigit() for ch in word)
        for word, nxt in zip(words, words[1:])
    )
