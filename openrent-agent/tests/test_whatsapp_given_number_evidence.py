"""Given-number evidence for WhatsApp matching (2026-10-08).

Real misses that stayed SAVED_UNMATCHED until linked by hand: the address the
landlord gave was only in the OpenRent chat (listing stored as an area), they
named our persona ("Harriet shared your number"), a same-name landlord in a
different district tied the right one, and the landlord's number was already
on the thread."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Account, Base, Conversation, Listing, Message, SearchProfile, WhatsAppHandoffIntent,
)
from app.whatsapp import handler, matcher

NOW = datetime(2026, 10, 8, 12, 0)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'wa.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(matcher, "SessionLocal", Session)
    return Session


def _thread(s, *, acct, persona, partner, thread, address, landlord, given_hours_ago=None,
            chat=(), phone=None, phone_found_hours_ago=None, intent=True):
    account = s.get(Account, acct)
    if account is None:
        account = Account(id=acct, email=f"{acct}@x", password="", persona_name=persona,
                          persona_partner_name=partner, active=True)
        s.add(account)
        s.flush()
        s.add(SearchProfile(id=acct, account_id=acct, location="X", active=True))
        s.flush()
    listing = Listing(listing_id=f"L{thread}", property_url=f"https://x/{thread}", search_profile_id=acct,
                      landlord_name=landlord, property_address=address, thread_id=thread, message_sent=True)
    s.add(listing)
    s.flush()
    given_at = NOW - timedelta(hours=given_hours_ago) if given_hours_ago is not None else None
    conv = Conversation(thread_id=thread, listing_id=listing.id, our_number_shared_at=given_at,
                        extracted_phone=phone,
                        phone_found_at=(NOW - timedelta(hours=phone_found_hours_ago)) if phone_found_hours_ago else None)
    s.add(conv)
    s.flush()
    for text in chat:
        s.add(Message(conversation_id=conv.id, direction="inbound", content=text,
                      created_at=NOW - timedelta(days=1)))
    if intent and given_at:
        s.add(WhatsAppHandoffIntent(thread_id=thread, listing_id=listing.id, landlord_name=landlord,
                                    property_address=address, created_at=given_at))
    s.commit()
    return thread


def _match(names, hints, texts, phone="447000000001"):
    cands, conf = matcher.match_by_evidence(
        names, hints, persona_names=matcher.mentioned_persona_names(texts),
        contact_phone=phone, inbound_texts=texts, contact_id=999, as_of=NOW,
    )
    return handler._match_status(cands, conf), (cands[0]["thread_id"] if cands else None), conf


def test_address_given_in_the_openrent_chat_decides(db):
    with db() as s:
        right = _thread(s, acct=27, persona="Nicola", partner="Chris", thread="46804739",
                        address="Church St, E16", landlord="Ashrafur R.", given_hours_ago=3,
                        chat=["I have appointment available on Thursday. Church Street, London, E16 2NB 2 Bed Flat"])
        _thread(s, acct=35, persona="Sophia", partner="Alice", thread="46768913",
                address="Cliveden Court, UB5", landlord="Christie N.", given_hours_ago=72)
    status, thread, _ = _match(["Mamun"], ["11 Church Street, London, E16 2NB"], ["Hi"])
    assert (status, thread) == ("MATCHED", right)


def test_same_name_in_a_different_district_is_ruled_out(db):
    with db() as s:
        right = _thread(s, acct=26, persona="Fatima", partner="Khalid", thread="46850257",
                        address="Chiswick, W4", landlord="Robert V.", given_hours_ago=6)
        _thread(s, acct=31, persona="Freya", partner="Freddie", thread="46339453",
                address="Mortimer Road, NW10", landlord="Robert N.", given_hours_ago=60)
    status, thread, _ = _match(
        ["Robert"], ["45 Kent Road, Chiswick, W4 5EY"],
        ["Hi there, It's Robert of 45 Kent Road in Chiswick. Just confirming the viewing Saturday at 1pm."],
    )
    assert (status, thread) == ("MATCHED", right)


def test_named_persona_narrows_to_that_account(db):
    with db() as s:
        right = _thread(s, acct=34, persona="Harriet", partner="George", thread="47015224",
                        address="Starling Court, SE2", landlord="Elif Y.", given_hours_ago=18)
        _thread(s, acct=34, persona="Harriet", partner="George", thread="47035538",
                address="Cascades Tower, E14", landlord="Andrew M.", given_hours_ago=1)
        _thread(s, acct=22, persona="Claire", partner="Marcus", thread="47000001",
                address="Bridle Road, CR0", landlord="Elif K.", given_hours_ago=2)
    status, thread, _ = _match(["Elif"], [], ["Hi George", "This is Elif", "Harriet shared your number"])
    assert (status, thread) == ("MATCHED", right)


def test_number_already_on_the_thread_is_certain(db):
    with db() as s:
        right = _thread(s, acct=23, persona="Jessica", partner="James", thread="46974597",
                        address="Stratford, E15", landlord="Nadarajah J.", given_hours_ago=1,
                        phone="07508173741", phone_found_hours_ago=5)
        _thread(s, acct=23, persona="Jessica", partner="James", thread="46497445",
                address="Proton Tower, E14", landlord="Wiyono A.", given_hours_ago=2)
    status, thread, conf = _match(["Senthuran"], ["24 Hatfield Road, E15 1QY"],
                                  ["Your partner Jessica provided your number"], phone="447508173741")
    assert (status, thread, conf) == ("MATCHED", right, matcher.PHONE_MATCH_CONFIDENCE)


def test_number_captured_after_they_wrote_does_not_count(db):
    with db() as s:
        _thread(s, acct=23, persona="Jessica", partner="James", thread="T1", address="Stratford, E15",
                landlord="A B.", given_hours_ago=1, phone="07508173741", phone_found_hours_ago=1)
    cands, _ = matcher.match_by_evidence(["Zed"], [], contact_phone="447508173741", inbound_texts=["Hi"],
                                         as_of=NOW - timedelta(days=30))
    assert all(c.get("reason") != "phone" for c in cands)


def test_timing_alone_never_links(db):
    with db() as s:
        _thread(s, acct=34, persona="Harriet", partner="George", thread="A", address="Starling Court, SE2",
                landlord="Elif Y.", given_hours_ago=1)
        _thread(s, acct=34, persona="Harriet", partner="George", thread="B", address="Cascades Tower, E14",
                landlord="Andrew M.", given_hours_ago=2)
    status, _, _ = _match([], [], ["Harriet shared your number"])
    assert status == "UNMATCHED"


def test_mentioned_accounts_include_partners_and_referral_verbs(db):
    with db() as s:
        s.add_all([
            Account(id=34, email="a@x", password="", persona_name="Harriet", persona_partner_name="George"),
            Account(id=22, email="b@x", password="", persona_name="Claire", persona_partner_name="Marcus"),
        ])
        s.commit()
        assert matcher.mentioned_account_ids(s, ["Hi George"]) == {34}
        assert matcher.mentioned_account_ids(s, ["Claire passed on your number"]) == {22}
        assert matcher.mentioned_account_ids(s, ["Morning, is the flat still free?"]) == set()


# ---- 2026-10-08 replay findings: what may and may not rule a thread out ----

@pytest.mark.parametrize("hints, stored, ruled_out", [
    (["Sydenham"], "Gibraltar House, SE26", False),             # a place, not a road
    (["198 River Heights"], "High Street, E15", False),         # a building on that street
    (["Flat 3, Christopher Bell Tower, 1 Pancras way, London, E3 2SR"], "Christopher Bell Tower, E3", False),
    (["Belgrave Gardens"], "St Johns Wood, NW8", False),        # "St" is Saint, an area
    (["the flat"], "London Road, CR4", False),                  # vague
    (["Chestnut Grove CR4"], "London Road, CR4", True),         # two different roads
    (["45 Kent Road, Chiswick, W4 5EY"], "Mortimer Road, NW10", True),  # other district
])
def test_address_rules_out_only_on_real_contradictions(hints, stored, ruled_out):
    assert matcher._address_rules_out(hints, stored) is ruled_out


def test_chat_needs_the_whole_street_phrase_or_postcode():
    assert matcher._chat_address_score("Flat 1A Austin House", "met Austin yesterday") == 0.0
    assert matcher._chat_address_score("Flat 1A Austin House", "it's in Austin House on Ewell Rd") == 88.0
    assert matcher._chat_address_score("11 Church Street, London, E16 2NB", "Church Street, London, E16 2NB") == 96.0


def test_surname_initial_separates_near_names():
    assert matcher._initial_agreement(["Allan Adams"], "Allan A.") > 0
    assert matcher._initial_agreement(["Allan Adams"], "Allan L.") < 0
    assert matcher._initial_agreement(["Allan Adams"], "Alan L.") == 0


def test_borderline_name_cannot_carry_a_listing_their_address_contradicts(db):
    """Replay 2026-10-08, contact 122: "Lauren regarding Malden rd" would have
    linked to Darren L. at Goosander Court NW9 on a 53 name score."""
    with db() as s:
        _thread(s, acct=29, persona="Isabelle", partner="Arthur", thread="46009698",
                address="Studio Flat, Goosander Court, NW9", landlord="Darren L.", given_hours_ago=20)
    status, _, _ = _match(["Lauren"], ["Malden Rd"], ["Morning it's Lauren regarding Malden rd"])
    assert status == "UNMATCHED"


@pytest.mark.parametrize("hint, specific", [
    ("Royal Victoria", False), ("Sydenham", False), ("Luton", False), ("the flat", False),
    ("Malden Rd", True), ("Chestnut Grove CR4", True), ("Austin House", True), ("IG11", True),
])
def test_area_names_are_not_specific_addresses(hint, specific):
    """Replay 2026-10-08, contact 111: "the appointment in Royal Victoria" must
    not count as an address contradicting Adriatic Apartments, E16."""
    assert matcher._hint_is_specific(hint) is specific
