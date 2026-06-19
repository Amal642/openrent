from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import (
    Account,
    Base,
    Conversation,
    LeadSheetExport,
    Listing,
    SearchProfile,
)


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "repo.db"
    engine = create_engine(f"sqlite:///{db_path}")
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", TestingSessionLocal)
    return TestingSessionLocal


def test_save_phone_number_sets_acquisition_timestamp(db_session):
    landlord_phone = "".join(("07", "123", "456", "789"))

    with db_session() as session:
        account = Account(email="a@example.com", password="", session_file="s.json")
        session.add(account)
        session.flush()
        account_id = account.id
        profile = SearchProfile(account_id=account.id, location="Leeds")
        session.add(profile)
        session.flush()
        listing = Listing(
            listing_id="L1",
            property_url="https://example.com/1",
            search_profile_id=profile.id,
        )
        session.add(listing)
        session.flush()
        conversation = Conversation(
            thread_id="T1",
            listing_id=listing.id,
            last_message_at=datetime.utcnow() - timedelta(days=2),
        )
        session.add(conversation)
        session.commit()

    repository.save_phone_number("T1", landlord_phone)

    with db_session() as session:
        conversation = session.query(Conversation).filter_by(thread_id="T1").one()
        assert conversation.phone_found is True
        assert conversation.phone_found_at is not None
        export = session.query(LeadSheetExport).filter_by(
            conversation_id=conversation.id
        ).one()
        assert export.status == "PENDING"
        assert export.next_attempt_at is not None

    assert repository.count_phones_today(account_id) == 1


def test_save_phone_number_resets_existing_sheet_export(db_session):
    with db_session() as session:
        account = Account(email="b@example.com", password="", session_file="s.json")
        session.add(account)
        session.flush()
        profile = SearchProfile(account_id=account.id, location="London")
        session.add(profile)
        session.flush()
        listing = Listing(
            listing_id="L3",
            property_url="https://www.openrent.co.uk/12345",
            search_profile_id=profile.id,
        )
        session.add(listing)
        session.flush()
        conversation = Conversation(thread_id="T3", listing_id=listing.id)
        session.add(conversation)
        session.flush()
        export = LeadSheetExport(
            conversation_id=conversation.id,
            status="EXPORTED",
            exported_at=datetime.utcnow(),
            destination_tab="June",
            destination_row=3,
        )
        session.add(export)
        session.commit()

    repository.save_phone_number("T3", "07123456789")

    with db_session() as session:
        export = session.query(LeadSheetExport).one()
        assert export.status == "PENDING"
        assert export.exported_at is None
        assert export.destination_tab == "June"
        assert export.destination_row == 3


def test_claim_due_sheet_exports_marks_rows_processing(db_session):
    with db_session() as session:
        account = Account(email="c@example.com", password="", session_file="s.json")
        session.add(account)
        session.flush()
        profile = SearchProfile(account_id=account.id, location="London")
        session.add(profile)
        session.flush()
        listing = Listing(
            listing_id="L4",
            property_url="https://www.openrent.co.uk/44444",
            search_profile_id=profile.id,
        )
        session.add(listing)
        session.flush()
        conversation = Conversation(
            thread_id="T4",
            listing_id=listing.id,
            extracted_phone="07123456780",
            phone_found_at=datetime.utcnow(),
        )
        session.add(conversation)
        session.flush()
        export = LeadSheetExport(
            conversation_id=conversation.id,
            status="PENDING",
            next_attempt_at=datetime.utcnow() - timedelta(minutes=1),
        )
        session.add(export)
        session.commit()
        export_id = export.id

    claimed = repository.claim_due_sheet_exports(
        limit=20,
        stale_minutes=15,
        max_attempts=8,
    )

    assert claimed == [export_id]
    with db_session() as session:
        export = session.query(LeadSheetExport).one()
        assert export.status == "PROCESSING"
        assert export.processing_started_at is not None


def test_mark_listing_skipped_is_not_processing_failure(db_session):
    with db_session() as session:
        listing = Listing(
            listing_id="L2",
            property_url="https://example.com/2",
            search_profile_id=None,
        )
        session.add(listing)
        session.commit()
        listing_id = listing.id

    repository.mark_listing_skipped(listing_id, reason="not_contactable")

    with db_session() as session:
        listing = session.query(Listing).filter_by(id=listing_id).one()
        assert listing.skip_reason == "not_contactable"
        assert listing.processing_failed is False


def test_ensure_account_persona_does_not_generate_mobile_number(db_session):
    with db_session() as session:
        account = Account(email="persona@example.com", password="", session_file="s.json")
        session.add(account)
        session.commit()
        account_id = account.id

    persona = repository.ensure_account_persona(account_id)

    assert persona["persona_type"]
    assert persona["mobile_number"] is None
