import asyncio
import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository as db_repository
from app.db.models import Base, Conversation, Listing, Message, WhatsAppContact
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
    monkeypatch.setattr(db_repository, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(repository, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(matcher, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(handler.settings, "WHATSAPP_AUTO_REPLY_ENABLED", False)
    monkeypatch.setattr(handler, "generate_closing_reply", lambda name=None: "Thanks")
    return TestingSessionLocal


def _seed_listing(
    session,
    *,
    name="Natalie",
    address="12 Loring Road, London",
    listing_id="LORING-1",
    thread_id="THREAD-1",
    landlord_id=123,
):
    listing = Listing(
        listing_id=listing_id,
        property_url="https://example.com/loring",
        landlord_id=landlord_id,
        landlord_name=name,
        property_address=address,
        thread_id=thread_id,
    )
    session.add(listing)
    session.flush()
    conversation = Conversation(thread_id=thread_id, listing_id=listing.id)
    session.add(conversation)
    session.commit()
    return listing.id


def test_incoming_message_matches_by_name_and_property(whatsapp_db, monkeypatch):
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: "Natalie")
    monkeypatch.setattr(
        handler, "extract_property_from_message", lambda text: "Loring road"
    )

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


def test_matching_accumulates_evidence_across_multiple_messages(
    whatsapp_db, monkeypatch
):
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


def test_incoming_message_matches_unique_landlord_by_whatsapp_name_only(
    whatsapp_db, monkeypatch
):
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: None)

    with whatsapp_db() as session:
        listing_pk = _seed_listing(
            session,
            name="Daryna W",
            address="44 Oak Street, London",
            listing_id="DARYNA-1",
            thread_id="THREAD-DARYNA",
        )

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="447534992400",
            message="Hello",
            sender_name="Daryna",
            jid="447534992400@s.whatsapp.net",
            message_id="MSG-DARYNA",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        conversation = (
            session.query(Conversation).filter_by(thread_id="THREAD-DARYNA").one()
        )

        assert contact.status == "PHONE_ACQUIRED"
        assert contact.match_status == "MATCHED"
        assert contact.listing_id == listing_pk
        assert contact.thread_id == "THREAD-DARYNA"
        assert contact.confidence == 90.0
        assert conversation.phone_found is True
        assert conversation.extracted_phone == "447534992400"


def test_incoming_message_does_not_match_ambiguous_landlord_name_only(
    whatsapp_db, monkeypatch
):
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: None)

    with whatsapp_db() as session:
        _seed_listing(
            session,
            name="Daryna W",
            address="44 Oak Street, London",
            listing_id="DARYNA-1",
            thread_id="THREAD-DARYNA-1",
            landlord_id=123,
        )
        _seed_listing(
            session,
            name="Daryna K",
            address="88 Pine Street, London",
            listing_id="DARYNA-2",
            thread_id="THREAD-DARYNA-2",
            landlord_id=456,
        )

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="447534992401",
            message="Hello",
            sender_name="Daryna",
            jid="447534992401@s.whatsapp.net",
            message_id="MSG-DARYNA-AMBIGUOUS",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        conversations = session.query(Conversation).all()

        assert contact.status == "AWAITING_PROPERTY"
        assert contact.match_status == "UNMATCHED"
        assert contact.listing_id is None
        assert contact.thread_id is None
        assert all(conversation.phone_found is False for conversation in conversations)


def test_incoming_message_with_no_name_or_property_asks_for_property_details(
    whatsapp_db, monkeypatch
):
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: None)
    monkeypatch.setattr(handler.settings, "WHATSAPP_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr(
        handler,
        "build_property_ask",
        lambda name=None, history=None: (
            "My wife manages the properties on OpenRent, can you please share "
            "the property details?"
        ),
    )
    monkeypatch.setattr(handler, "next_reply_time", lambda: datetime.utcnow())

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="447534992402",
            message="Hello",
            sender_name=None,
            jid="447534992402@s.whatsapp.net",
            message_id="MSG-NO-EVIDENCE",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()

        assert contact.status == "AWAITING_PROPERTY"
        assert contact.match_status == "UNMATCHED"
        assert contact.property_ask_count == 1
        assert "wife manages the properties on OpenRent" in contact.last_ai_reply
        assert "property details" in contact.last_ai_reply


def test_closed_whatsapp_contact_does_not_schedule_another_closing(
    whatsapp_db, monkeypatch
):
    monkeypatch.setattr(handler.settings, "WHATSAPP_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: "Natalie")
    monkeypatch.setattr(
        handler, "extract_property_from_message", lambda text: "Loring Road"
    )
    monkeypatch.setattr(
        handler, "generate_closing_reply", lambda name=None: "Thanks again"
    )

    with whatsapp_db() as session:
        session.add(
            WhatsAppContact(
                phone_number="447534992499",
                name="Natalie",
                status="SAVED_UNMATCHED",
                first_message="Property 123",
                last_message="Thanks for reaching out",
                message_history=json.dumps(
                    [
                        {
                            "direction": "inbound",
                            "message": "Property 123",
                            "received_at": datetime.utcnow().isoformat(),
                        },
                        {
                            "direction": "outbound",
                            "message": "Thanks for reaching out",
                            "received_at": datetime.utcnow().isoformat(),
                        },
                    ]
                ),
                last_received_at=datetime.utcnow(),
            )
        )
        session.commit()

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="447534992499",
            message="Ok bro no worries",
            sender_name="Natalie",
            message_id="MSG-CLOSED",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        history = json.loads(contact.message_history)

        assert contact.status == "SAVED_UNMATCHED"
        assert contact.reply_scheduled_at is None
        assert contact.last_ai_reply is None
        assert [item["direction"] for item in history].count("outbound") == 1


def test_whatsapp_contact_stops_after_three_regular_outbound_messages(
    whatsapp_db, monkeypatch
):
    monkeypatch.setattr(handler.settings, "WHATSAPP_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(handler, "extract_property_from_message", lambda text: None)
    monkeypatch.setattr(
        handler, "build_property_ask", lambda name=None, history=None: "Which property?"
    )

    with whatsapp_db() as session:
        session.add(
            WhatsAppContact(
                phone_number="447534992500",
                status="AWAITING_PROPERTY",
                first_message="Hi",
                last_message="Third reply",
                message_history=json.dumps(
                    [
                        {
                            "direction": "outbound",
                            "message": "First reply",
                            "received_at": datetime.utcnow().isoformat(),
                        },
                        {
                            "direction": "outbound",
                            "message": "Second reply",
                            "received_at": datetime.utcnow().isoformat(),
                        },
                        {
                            "direction": "outbound",
                            "message": "Third reply",
                            "received_at": datetime.utcnow().isoformat(),
                        },
                    ]
                ),
                last_received_at=datetime.utcnow(),
            )
        )
        session.commit()

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="447534992500",
            message="hmm",
            message_id="MSG-MAX",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()

        assert contact.status == "MAX_REPLIES_REACHED"
        assert contact.reply_scheduled_at is None
        assert contact.last_ai_reply is None


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


def test_viewing_message_cancels_after_first_message_creates_match(
    whatsapp_db,
    monkeypatch,
):
    sent = []

    class FakeWorker:
        async def send_message(self, phone, message):
            sent.append((phone, message))
            return True

    monkeypatch.setattr(handler.settings, "WHATSAPP_AUTO_REPLY_ENABLED", True)
    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: "Ros")
    monkeypatch.setattr(
        handler,
        "extract_property_from_message",
        lambda text: "Flat 3, 14 Rochdale Way SE8 4LY",
    )
    monkeypatch.setattr(
        "app.ai.replies.generate_cancellation_message",
        lambda history: ("Sorry, we need to cancel the viewing today.", None),
    )
    monkeypatch.setattr(
        "app.whatsapp.browser_worker.get_worker",
        lambda: FakeWorker(),
    )

    with whatsapp_db() as session:
        _seed_listing(
            session,
            name="Ros",
            address="Flat 3, 14 Rochdale Way SE8 4LY",
            listing_id="ROCHDALE-1",
            thread_id="THREAD-ROCHDALE",
            landlord_id=456,
        )
        conversation = (
            session.query(Conversation).filter_by(thread_id="THREAD-ROCHDALE").one()
        )
        conversation.conversation_stage = "VIEWING_BOOKED"
        conversation.cancel_required = True
        session.commit()

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="447534992450",
            message=(
                "The flat address is: Flat 3, 14 Rochdale Way SE8 4LY. "
                "I will meet you there for the viewing today at 1.30."
            ),
            sender_name="Ros",
            message_id="MSG-VIEWING-MATCH",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        conversation = (
            session.query(Conversation).filter_by(thread_id="THREAD-ROCHDALE").one()
        )
        messages = (
            session.query(Message)
            .filter_by(conversation_id=conversation.id)
            .order_by(Message.id)
            .all()
        )

        assert sent == [("447534992450", "Sorry, we need to cancel the viewing today.")]
        assert contact.status == "CANCELLED"
        assert contact.last_ai_reply is None
        assert contact.thread_id == "THREAD-ROCHDALE"
        assert conversation.viewing_cancelled is True
        assert [message.direction for message in messages] == ["inbound", "outbound"]


def test_linked_whatsapp_reply_unblocks_reactive_cancellation(
    whatsapp_db,
    monkeypatch,
):
    sent = []

    class FakeWorker:
        async def send_message(self, phone, message):
            sent.append((phone, message))
            return True

    monkeypatch.setattr(
        "app.ai.replies.generate_cancellation_message",
        lambda history: ("Sorry, we cannot make the viewing now.", None),
    )
    monkeypatch.setattr(
        "app.whatsapp.browser_worker.get_worker",
        lambda: FakeWorker(),
    )

    requested_at = datetime(2026, 7, 24, 10, 0, 0)
    with whatsapp_db() as session:
        listing_id = _seed_listing(
            session,
            name="Sam Wilkins",
            address="Flat 3, 14 Rochdale Way SE8 4LY",
            listing_id="ROCHDALE-2",
            thread_id="THREAD-SAM",
            landlord_id=789,
        )
        conversation = (
            session.query(Conversation).filter_by(thread_id="THREAD-SAM").one()
        )
        conversation.conversation_stage = "VIEWING_BOOKED"
        conversation.cancel_required = True
        conversation.phone_requested_at = requested_at
        session.add(
            WhatsAppContact(
                phone_number="447534992451",
                listing_id=listing_id,
                thread_id="THREAD-SAM",
                status="PHONE_ACQUIRED",
                message_history=json.dumps([]),
            )
        )
        session.commit()

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="447534992451",
            message="Does this mean you're attending or not as I have other appointments?",
            timestamp=1784892000,
            sender_name="Sam",
            message_id="MSG-ATTENDING",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        conversation = (
            session.query(Conversation).filter_by(thread_id="THREAD-SAM").one()
        )
        inbound = (
            session.query(Message)
            .filter_by(
                conversation_id=conversation.id,
                direction="inbound",
            )
            .one()
        )

        assert sent == [("447534992451", "Sorry, we cannot make the viewing now.")]
        assert contact.status == "CANCELLED"
        assert conversation.viewing_cancelled is True
        assert inbound.created_at > requested_at


def test_saved_unmatched_contact_rematches_and_cancels_on_frustrated_followup(
    whatsapp_db, monkeypatch
):
    """A contact we'd already closed out as SAVED_UNMATCHED sends a follow-up
    with the actual property address plus clear access/no-show frustration.
    Even though the CRM never flagged this conversation as VIEWING_BOOKED
    (the viewing was only ever arranged over WhatsApp), the landlord's own
    words should be enough to re-match and send a reactive cancellation."""
    sent = []

    class FakeWorker:
        async def send_message(self, phone, message):
            sent.append((phone, message))
            return True

    monkeypatch.setattr(handler, "extract_name_from_message", lambda text: None)
    monkeypatch.setattr(
        handler,
        "extract_property_from_message",
        lambda text: "24 Burnham Gardens, TW4 6LR",
    )
    monkeypatch.setattr(
        "app.ai.replies.generate_cancellation_message",
        lambda history: ("Sorry, we need to cancel — thanks for your patience.", None),
    )
    monkeypatch.setattr(
        "app.whatsapp.browser_worker.get_worker",
        lambda: FakeWorker(),
    )

    with whatsapp_db() as session:
        _seed_listing(
            session,
            name="Priya",
            address="24 Burnham Gardens, TW4 6LR",
            listing_id="BURNHAM-1",
            thread_id="THREAD-BURNHAM",
            landlord_id=999,
        )
        session.add(
            WhatsAppContact(
                phone_number="447534992460",
                status="SAVED_UNMATCHED",
                message_history=json.dumps([]),
            )
        )
        session.commit()

    asyncio.run(
        handler.handle_incoming_message(
            phone_number="447534992460",
            message=(
                "24 Burnham gardens tw46lr, been waititng since 1pm, "
                "can't wait any further, call me asap"
            ),
            sender_name=None,
            message_id="MSG-BURNHAM-FOLLOWUP",
        )
    )

    with whatsapp_db() as session:
        contact = session.query(WhatsAppContact).one()
        conversation = (
            session.query(Conversation).filter_by(thread_id="THREAD-BURNHAM").one()
        )

        assert sent == [
            ("447534992460", "Sorry, we need to cancel — thanks for your patience.")
        ]
        assert contact.status == "CANCELLED"
        assert contact.thread_id == "THREAD-BURNHAM"
        assert conversation.viewing_cancelled is True
