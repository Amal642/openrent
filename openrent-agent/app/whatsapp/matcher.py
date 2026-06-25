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
from app.db.models import Listing
from app.utils.logger import logger

_client = OpenAI(api_key=settings.OPENAI_API_KEY, timeout=15.0)

# Auto-link confidence threshold (%)
AUTO_LINK_THRESHOLD = 65.0

# Greeting words to strip from extracted names
_STRIP_WORDS = {
    "hello", "hi", "hey", "good", "morning", "afternoon", "evening",
    "thanks", "thank", "you", "please", "there",
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


def extract_name_from_message(text: str) -> Optional[str]:
    """Try regex patterns first; fall back to LLM for messages >= 3 words."""
    for pattern in _NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            name = match.group(1).strip()
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
            model="gpt-4.1-mini",
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
            model="gpt-4.1-mini",
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
        listings = db.query(Listing).filter(Listing.landlord_name.isnot(None)).all()

        results = []
        for listing in listings:
            if not listing.landlord_name:
                continue
            sim = _similarity(name, listing.landlord_name)
            if sim >= 40:  # minimum to consider
                results.append({
                    "listing_id": listing.id,
                    "listing_listing_id": listing.listing_id,
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
            .filter(Listing.property_address.isnot(None))
            .all()
        )

        best = None
        best_score = 0.0

        for listing in listings:
            if not listing.property_address:
                continue
            addr_sim = _similarity(property_hint, listing.property_address)

            # Combine name similarity if we have a name
            score = addr_sim
            if name and listing.landlord_name:
                name_sim = _similarity(name, listing.landlord_name)
                # Weight: 60% address, 40% name
                score = addr_sim * 0.6 + name_sim * 0.4
                if name_sim > 50 and addr_sim > 50:
                    score = min(95.0, score + 10)

            if score > best_score:
                best_score = score
                best = {
                    "listing_id": listing.id,
                    "listing_listing_id": listing.listing_id,
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
