"""Give-out activation tests: reactive WhatsApp number share + handoff recording.

When the landlord asks for our number and is reluctant to share theirs (and we
have already asked once), generate_reply takes the deterministic phone-share
shortcut: it hands out the husband's WhatsApp number, framed as WhatsApp only
(the number is call/SMS-dead). On a real OpenRent thread that share must also
record a WhatsAppHandoffIntent so a later inbound WhatsApp maps back to the
property (see whatsapp.matcher._apply_handoff_prior).

This path is NOT reachable from the sim lab (it routes build_reply_prompt only,
never generate_reply), so these faithful tests drive generate_reply directly.
"""
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.ai import replies
from app.db.models import Base, Conversation, Listing, WhatsAppHandoffIntent
from app.whatsapp import repository as wa_repository

GIVE_OUT = "07599390221"


@pytest.fixture()
def handoff_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'handoff.db'}")
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(wa_repository, "SessionLocal", TestingSessionLocal)
    return TestingSessionLocal


def _seed_thread(session, thread_id="THREAD-GO", name="Priya", address="9 Elm Road, London"):
    listing = Listing(
        listing_id="GO-1",
        property_url="https://example.com/go-1",
        landlord_id=77,
        landlord_name=name,
        property_address=address,
        thread_id=thread_id,
    )
    session.add(listing)
    session.flush()
    session.add(Conversation(thread_id=thread_id, listing_id=listing.id))
    session.commit()


def _force_shortcut(monkeypatch, *, asked=True, hesitant=True, shared=False, asks=1):
    """Drive the generate_reply gate deterministically, so no LLM call happens."""
    monkeypatch.setattr(replies, "latest_landlord_asked_for_phone", lambda m: asked)
    monkeypatch.setattr(replies, "latest_landlord_hesitant_about_phone", lambda m: hesitant)
    monkeypatch.setattr(replies, "phone_shared_state", lambda m, p, conversation=None: shared)
    monkeypatch.setattr(replies, "detect_screening_questions", lambda m: [])
    monkeypatch.setattr(replies, "count_number_asks", lambda m: asks)
    monkeypatch.setattr(replies, "outbound_count", lambda m: asks)


def test_giveout_shares_whatsapp_number_and_records_handoff(handoff_db, monkeypatch):
    _force_shortcut(monkeypatch)
    with handoff_db() as session:
        _seed_thread(session)

    persona = {"persona_name": "Alex", "mobile_number": GIVE_OUT}
    messages = [{"sender": "landlord", "message": "Can you share your number? I'd rather keep mine private for now."}]

    reply, error = replies.generate_reply(
        messages, stage="VIEWING_DISCUSSION", persona=persona, thread_id="THREAD-GO"
    )

    assert error is None
    assert GIVE_OUT in reply  # exact number survives the validator
    assert "whatsapp" in reply.lower()  # framed as WhatsApp, not a call line
    assert "—" not in reply and "–" not in reply  # no em/en dash tell
    assert " ," not in reply  # dash->comma cleanup left no stray space
    # We never solicit the landlord's number in the same breath.
    with handoff_db() as session:
        intents = session.query(WhatsAppHandoffIntent).all()
        assert len(intents) == 1
        assert intents[0].thread_id == "THREAD-GO"
        assert intents[0].landlord_name == "Priya"
        assert intents[0].property_address == "9 Elm Road, London"
        assert intents[0].matched_contact_id is None


def test_giveout_does_not_fire_without_mobile_number(handoff_db, monkeypatch):
    """No provisioned number -> shortcut is skipped and nothing is recorded.
    We stub the LLM path so the test never calls OpenAI."""
    _force_shortcut(monkeypatch)
    monkeypatch.setattr(
        replies,
        "generate_reply_result",
        lambda *a, **k: SimpleNamespace(reply="Happy to sort a viewing, when suits you?", is_valid=True, error=None),
    )
    with handoff_db() as session:
        _seed_thread(session)

    persona = {"persona_name": "Alex"}  # no mobile_number
    messages = [{"sender": "landlord", "message": "What's your number?"}]

    reply, error = replies.generate_reply(
        messages, stage="VIEWING_DISCUSSION", persona=persona, thread_id="THREAD-GO"
    )

    assert error is None
    assert GIVE_OUT not in reply
    with handoff_db() as session:
        assert session.query(WhatsAppHandoffIntent).count() == 0


def test_giveout_does_not_fire_when_landlord_not_hesitant(handoff_db, monkeypatch):
    """Landlord asked but is willing to share theirs -> stay on OpenRent, no share."""
    _force_shortcut(monkeypatch, hesitant=False)
    monkeypatch.setattr(
        replies,
        "generate_reply_result",
        lambda *a, **k: SimpleNamespace(reply="Sure, what times work for a viewing?", is_valid=True, error=None),
    )
    with handoff_db() as session:
        _seed_thread(session)

    persona = {"persona_name": "Alex", "mobile_number": GIVE_OUT}
    messages = [{"sender": "landlord", "message": "Whats your number, I'll send you mine too"}]

    reply, error = replies.generate_reply(
        messages, stage="VIEWING_DISCUSSION", persona=persona, thread_id="THREAD-GO"
    )

    assert error is None
    assert GIVE_OUT not in reply
    with handoff_db() as session:
        assert session.query(WhatsAppHandoffIntent).count() == 0


def test_record_handoff_helper_is_guarded(handoff_db, monkeypatch):
    """The recorder only fires on a real thread with the number actually present,
    and never raises into the reply path."""
    with handoff_db() as session:
        _seed_thread(session)

    # No thread_id -> no record (sim-lab / non-thread callers).
    replies._record_handoff_if_shared(None, f"his WhatsApp is {GIVE_OUT}", GIVE_OUT)
    # Number not present in the reply -> no record.
    replies._record_handoff_if_shared("THREAD-GO", "Happy to arrange a viewing", GIVE_OUT)
    with handoff_db() as session:
        assert session.query(WhatsAppHandoffIntent).count() == 0

    # Real thread + number present (formatting differences ignored) -> records once.
    replies._record_handoff_if_shared("THREAD-GO", "reach him on 07599 390221 on whatsapp", GIVE_OUT)
    with handoff_db() as session:
        assert session.query(WhatsAppHandoffIntent).count() == 1
