import asyncio
import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, Conversation, Listing, WhatsAppContact
from app.whatsapp import handler, matcher, repository


def test_name_extraction_does_not_include_owner_phrase():
    assert (
        matcher.extract_name_from_message(
            "Hi mary this is Natalie the owner of the house on Loring road."
        )
        == "Natalie"
    )


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
    monkeypatch.setattr(repository, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(matcher, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(handler.settings, "WHATSAPP_AUTO_REPLY_ENABLED", False)
    monkeypatch.setattr(handler, "generate_closing_reply", lambda name=None: "Thanks")
    return TestingSessionLocal


def _seed_listing(session, *, name="Natalie", address="12 Loring Road, London"):
    listing = Listing(
        listing_id="LORING-1",
        property_url="https://example.com/loring",
        landlord_id=123,
        landlord_name=name,
        property_address=address,
        thread_id="THREAD-1",
    )
    session.add(listing)
    session.flush()
    conversation = Conversation(thread_id="THREAD-1", listing_id=listing.id)
    session.add(conversation)
    session.commit()
    return listing.id


def test_incoming_message_matches_by_name_and_property(whatsapp_db, monkeypatch):
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: "Natalie")
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: "Loring road")

    with whatsapp_db() as session:
        listing_pk = _seed_listing(session)

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="447534992399",
            message="Hi Mary this is Natalie, owner of the house on Loring road.",
            timestamp=1_719_300_000,
            sender_name="Natalie",
            jid="447534992399@s.whatsapp.net",
            message_id="MSG1",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        conversation = session.query(Conversation).filter_by(thread_id="THREAD-1").one()

        assert contact.status == "PHONE_ACQUIRED"
        assert contact.match_status == "MATCHED"
        assert contact.listing_id == listing_pk
        assert contact.thread_id == "THREAD-1"
        assert contact.reply_scheduled_at is None
        assert contact.last_ai_reply is None
        assert conversation.phone_found is True
        assert conversation.extracted_phone == "447534992399"
        assert conversation.status == "PHONE_ACQUIRED"


def test_matching_accumulates_evidence_across_multiple_messages(whatsapp_db, monkeypatch):
    with whatsapp_db() as session:
        _seed_listing(session, name="Sam Owner", address="88 Loring Road, London")

    def fake_name(text):
        return "Sam Owner" if "Sam" in text else None

    def fake_property(text):
        return "Loring Road" if "Loring" in text else None

    monkeypatch.setattr(handler, "extract_name_from_message", fake_name)
    monkeypatch.setattr(handler, "extract_property_from_message", fake_property)

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="lid:235918409633988",
            message="Hi, can we arrange this?",
            sender_name=None,
            jid="235918409633988@lid",
            message_id="M1",
        )
    )
    asyncio.run(
        handler.handle_incoming_message(
            phone_number="lid:235918409633988",
            message="This is Sam Owner, about Loring Road",
            sender_name=None,
            jid="235918409633988@lid",
            message_id="M2",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        history = json.loads(contact.message_history)
        conversation = session.query(Conversation).one()

        assert len(history) == 2
        assert contact.lid == "235918409633988"
        assert contact.status == "PHONE_ACQUIRED"
        assert contact.match_status == "MATCHED"
        assert conversation.phone_found is True
        assert conversation.extracted_phone == "lid:235918409633988"


def test_lid_resolution_updates_existing_contact(whatsapp_db):
    with whatsapp_db() as session:
        session.add(
            WhatsAppContact(
                phone_number="lid:235918409633988",
                lid="235918409633988",
                name="Natalie",
                first_message="Hello",
                last_message="Hello",
                last_received_at=datetime.utcnow(),
            )
        )
        session.commit()

    contact = repository.resolve_lid_to_phone(
        "235918409633988",
        "447534992399",
        "447534992399@s.whatsapp.net",
    )

    with whatsapp_db() as session:
        contacts = session.query(WhatsAppContact).all()
        assert len(contacts) == 1
        assert contact.phone_number == "447534992399"
        assert contacts[0].phone_number == "447534992399"
        assert contacts[0].lid == "235918409633988"
