"""Handoff-intent WhatsApp matcher tests.

When the AI shares the husband's WhatsApp number on an OpenRent thread we record
a WhatsAppHandoffIntent. A later inbound WhatsApp from that landlord should then
match back to the correct property/thread even when name-only evidence would
otherwise be ambiguous — WITHOUT loosening MATCH_THRESHOLD / AUTO_MATCH_MIN_GAP.

The baseline (no intent) is covered by
test_whatsapp_matching.test_incoming_message_does_not_match_ambiguous_landlord_name_only:
two "Daryna" landlords, name-only -> UNMATCHED. These tests add the missing prior.
"""
import asyncio
import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository as db_repository
from app.db.models import (
    Base,
    Conversation,
    Listing,
    WhatsAppContact,
    WhatsAppHandoffIntent,
)
from app.whatsapp import handler, matcher, repository


@pytest.fixture()
def whatsapp_db(tmp_path, monkeypatch):
    db_path = tmp_path / "whatsapp.db"
    engine = create_engine(f"sqlite:///{db_path}")
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(db_repository, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(repository, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(matcher, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(handler.settings, "WHATSAPP_AUTO_REPLY_ENABLED", False)
    monkeypatch.setattr(handler, "generate_closing_reply", lambda name=None: "Thanks")
    return TestingSessionLocal


def _seed_listing(
    session,
    *,
    name,
    address,
    listing_id,
    thread_id,
    landlord_id,
):
    listing = Listing(
        listing_id=listing_id,
        property_url=f"https://example.com/{listing_id}",
        landlord_id=landlord_id,
        landlord_name=name,
        property_address=address,
        thread_id=thread_id,
    )
    session.add(listing)
    session.flush()
    session.add(Conversation(thread_id=thread_id, listing_id=listing.id))
    session.commit()
    return listing.id


def _seed_two_darynas(session):
    """The ambiguous baseline: two different 'Daryna' landlords, so a name-only
    inbound cannot be resolved without an extra signal."""
    pk1 = _seed_listing(
        session,
        name="Daryna W",
        address="44 Oak Street, London",
        listing_id="DARYNA-1",
        thread_id="THREAD-DARYNA-1",
        landlord_id=123,
    )
    pk2 = _seed_listing(
        session,
        name="Daryna K",
        address="88 Pine Street, London",
        listing_id="DARYNA-2",
        thread_id="THREAD-DARYNA-2",
        landlord_id=456,
    )
    return pk1, pk2


def _inbound_from_daryna(phone, message_id):
    asyncio.run(
        handler.handle_incoming_message(
            phone_number=phone,
            message="Hello",
            sender_name="Daryna",
            jid=f"{phone}@s.whatsapp.net",
            message_id=message_id,
        )
    )


def test_record_handoff_intent_snapshots_listing(whatsapp_db):
    """record_handoff_intent pulls landlord name + address off the thread's
    Listing so the matcher has something to score against later."""
    with whatsapp_db() as session:
        _seed_two_darynas(session)

    intent = repository.record_handoff_intent("THREAD-DARYNA-2")

    assert intent is not None
    assert intent.thread_id == "THREAD-DARYNA-2"
    assert intent.landlord_name == "Daryna K"
    assert intent.property_address == "88 Pine Street, London"
    assert intent.matched_contact_id is None


def test_record_handoff_intent_is_idempotent_per_thread(whatsapp_db):
    """Handing the number out twice on the same thread should not stack
    duplicate unconsumed intents."""
    with whatsapp_db() as session:
        _seed_two_darynas(session)

    first = repository.record_handoff_intent("THREAD-DARYNA-2")
    second = repository.record_handoff_intent("THREAD-DARYNA-2")

    assert first.id == second.id
    with whatsapp_db() as session:
        assert session.query(WhatsAppHandoffIntent).count() == 1


def test_handoff_intent_disambiguates_ambiguous_name(whatsapp_db, monkeypatch):
    """The core fix: name-only inbound that was UNMATCHED baseline now matches
    the thread we recently handed the number to."""
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: None)

    with whatsapp_db() as session:
        _, pk2 = _seed_two_darynas(session)

    # We handed the WhatsApp number out on Daryna K's thread.
    repository.record_handoff_intent("THREAD-DARYNA-2")

    _inbound_from_daryna("447534992401", "MSG-HANDOFF-DISAMBIG")

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        assert contact.match_status == "MATCHED"
        assert contact.status == "PHONE_ACQUIRED"
        assert contact.listing_id == pk2
        assert contact.thread_id == "THREAD-DARYNA-2"


def test_no_handoff_intent_leaves_ambiguous_name_unmatched(whatsapp_db, monkeypatch):
    """Additive/inert guarantee: with no intent, the ambiguous name-only inbound
    still stays UNMATCHED exactly as before the feature."""
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: None)

    with whatsapp_db() as session:
        _seed_two_darynas(session)

    _inbound_from_daryna("447534992402", "MSG-NO-INTENT")

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        assert contact.match_status == "UNMATCHED"
        assert contact.status == "AWAITING_PROPERTY"
        assert contact.thread_id is None


def test_two_recent_handoffs_same_name_stays_unmatched(whatsapp_db, monkeypatch):
    """Gap logic preserved: if BOTH ambiguous landlords were recently handed the
    number, a name-only inbound is genuinely ambiguous and must NOT auto-match —
    it should fall back to asking which property."""
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: None)

    with whatsapp_db() as session:
        _seed_two_darynas(session)

    repository.record_handoff_intent("THREAD-DARYNA-1")
    repository.record_handoff_intent("THREAD-DARYNA-2")

    _inbound_from_daryna("447534992403", "MSG-TWO-INTENTS")

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        assert contact.match_status == "UNMATCHED"
        assert contact.thread_id is None


def test_stale_handoff_intent_is_ignored(whatsapp_db, monkeypatch):
    """A handoff older than the 7-day window must not resurrect a match."""
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: None)

    with whatsapp_db() as session:
        _seed_two_darynas(session)
        session.add(
            WhatsAppHandoffIntent(
                thread_id="THREAD-DARYNA-2",
                listing_id=None,
                landlord_name="Daryna K",
                property_address="88 Pine Street, London",
                created_at=datetime.utcnow() - timedelta(days=9),
            )
        )
        session.commit()

    _inbound_from_daryna("447534992404", "MSG-STALE-INTENT")

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        assert contact.match_status == "UNMATCHED"
        assert contact.thread_id is None


def _seed_sent_listing(session, *, name, address, listing_id, thread_id):
    listing = Listing(
        listing_id=listing_id,
        property_url=f"https://example.com/{listing_id}",
        landlord_name=name,
        property_address=address,
        thread_id=thread_id,
        message_sent=True,
    )
    session.add(listing)
    session.flush()
    session.add(Conversation(thread_id=thread_id, listing_id=listing.id))
    session.commit()
    return listing.id


def test_named_street_beats_same_district_listing(whatsapp_db):
    """2026-09-30 regression (contact 392): the persona handed the number to 3
    landlords in one minute; one wrote "is this Nicola?" then named "Bedonwell
    Road DA17 5NZ". A different listing in the same DA17 district tied at 90 vs
    90.8, so it stayed UNMATCHED. The named street must now win clearly, while
    the name-only first message stays ambiguous (asks which property)."""
    with whatsapp_db() as session:
        bedonwell = _seed_sent_listing(session, name="Anterpreet S.", address="Bedonwell Road, DA17",
                                       listing_id="L-BED", thread_id="T-BED")
        _seed_sent_listing(session, name="H S.", address="Wadeville Close, DA17",
                           listing_id="L-WADE", thread_id="T-WADE")
        _seed_sent_listing(session, name="Nayem K.", address="Goldsmith Avenue, E12",
                           listing_id="L-GOLD", thread_id="T-GOLD")
        _seed_sent_listing(session, name="Ashrafur R.", address="Church St, E16",
                           listing_id="L-CHURCH", thread_id="T-CHURCH")
        # Fuzzy look-alike in another district, also recently handed the number.
        _seed_sent_listing(session, name="Ravi P.", address="Well Road, EN5",
                           listing_id="L-WELL", thread_id="T-WELL")
    for thread in ("T-BED", "T-GOLD", "T-CHURCH", "T-WELL"):
        repository.record_handoff_intent(thread)

    candidates, confidence = matcher.match_by_evidence(["Nicola"], [])
    assert handler._match_status(candidates, confidence) == "UNMATCHED"

    candidates, confidence = matcher.match_by_evidence(["Nicola"], ["Bedonwell Road DA17 5NZ"])
    assert handler._match_status(candidates, confidence) == "MATCHED"
    assert candidates[0]["listing_id"] == bedonwell
    assert candidates[0]["confidence"] - candidates[1]["confidence"] >= handler.AUTO_MATCH_MIN_GAP


@pytest.mark.parametrize("hint,stored,expected", [
    ("Bedonwell Road DA17 5NZ", "Bedonwell Road, DA17", 96.0),   # street + district
    ("Bedonwell Road DA17 5NZ", "Wadeville Close, DA17", 70.0),  # wrong street, same district
    ("DA17 5NZ", "Wadeville Close, DA17", 90.0),                 # postcode only: district still counts
    ("Bedonwell Road DA17 5NZ", "Well Road, EN5", 30.0),         # other district: capped, not a look-alike
    ("Bedonwell Road", "Bedonwell Road, DA17", 92.0),            # no postcode in hint: unchanged
])
def test_property_score_street_vs_district(hint, stored, expected):
    assert matcher._property_score(hint, stored) == expected


def test_named_building_beats_generic_word_lookalikes(whatsapp_db):
    """2026-10-01 regression (contact 398): "Inga from Tothill house Page street"
    stayed UNMATCHED at 90.5 vs 86.0 for "Horizon House, BR8" (shared generic
    word "House" + a recent handoff). Distinctive words decide now."""
    with whatsapp_db() as session:
        inga = _seed_sent_listing(session, name="Inga N.", address="Tothill House, SW1P",
                                  listing_id="L-TOT", thread_id="T-TOT")
        _seed_sent_listing(session, name="Ionela C.", address="Horizon House, BR8",
                           listing_id="L-HOR", thread_id="T-HOR")
        _seed_sent_listing(session, name="Gina R.", address="Ongar Road, SW6",
                           listing_id="L-ONG", thread_id="T-ONG")
    for thread in ("T-TOT", "T-HOR", "T-ONG"):
        repository.record_handoff_intent(thread)

    candidates, confidence = matcher.match_by_evidence(
        ["Scion Mastery/Angloslav", "Inga"], ["Tothill House, Page Street"]
    )
    assert handler._match_status(candidates, confidence) == "MATCHED"
    assert candidates[0]["listing_id"] == inga


@pytest.mark.parametrize("hint,stored,expected", [
    ("Tothill House, Page Street", "Tothill House, SW1P", 75.0),  # shares the building name
    ("Tothill House, Page Street", "Horizon House, BR8", 30.0),   # only generic "House" shared
    ("the flat on Goldsmith Avenue", "Goldsmith Avenue, E12", 88.0),
    ("Elm Road", "Elm Park, RM12", 30.0),                          # same word, different street type
    ("Elm Road", "Elm Road, RM12", 92.0),
])
def test_property_score_distinctive_words(hint, stored, expected):
    assert matcher._property_score(hint, stored) == expected


def test_same_name_different_street_type_in_same_district_is_not_a_match():
    # Found in the 2026-10-01 audit: "Farmers Close, SL9" scored 96 against
    # "Farmers Place, SL9".
    assert matcher._property_score("Farmers Close, SL9", "Farmers Place, SL9") == 70.0
    assert matcher._property_score("Farmers Close, SL9", "Farmers Close, SL9") >= 96.0
