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
        profile = SearchProfile(account_id=account.id, location="London")
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


def test_save_phone_number_does_not_queue_non_london_sheet_export(db_session):
    with db_session() as session:
        account = Account(email="north@example.com", password="", session_file="s.json")
        session.add(account)
        session.flush()
        profile = SearchProfile(account_id=account.id, location="Manchester")
        session.add(profile)
        session.flush()
        listing = Listing(
            listing_id="M1",
            property_url="https://example.com/m1",
            search_profile_id=profile.id,
        )
        session.add(listing)
        session.flush()
        session.add(Conversation(thread_id="M-T1", listing_id=listing.id))
        session.commit()

    repository.save_phone_number("M-T1", "07123456789")

    with db_session() as session:
        conversation = session.query(Conversation).filter_by(thread_id="M-T1").one()
        assert conversation.phone_found is True
        assert conversation.status == "PHONE_ACQUIRED"
        assert session.query(LeadSheetExport).count() == 0


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


def test_reset_sheet_export_by_listing_id(db_session):
    with db_session() as session:
        account = Account(email="d@example.com", password="", session_file="s.json")
        session.add(account)
        session.flush()
        profile = SearchProfile(account_id=account.id, location="Orpington")
        session.add(profile)
        session.flush()
        listing = Listing(
            listing_id="2872199",
            property_url="https://www.openrent.co.uk/2872199",
            search_profile_id=profile.id,
        )
        session.add(listing)
        session.flush()
        conversation = Conversation(thread_id="T5", listing_id=listing.id)
        session.add(conversation)
        session.flush()
        export = LeadSheetExport(
            conversation_id=conversation.id,
            status="EXPORTED",
            destination_tab="June",
            destination_row=355,
        )
        session.add(export)
        session.commit()
        export_id = export.id

    result = repository.reset_sheet_export_by_listing_id("2872199")

    assert result == export_id
    with db_session() as session:
        export = session.query(LeadSheetExport).one()
        assert export.status == "PENDING"
        assert export.next_attempt_at is not None


def test_backfill_sheet_export_outbox_filters_location(db_session):
    with db_session() as session:
        account = Account(email="backfill@example.com", password="", session_file="s.json")
        session.add(account)
        session.flush()

        london = SearchProfile(account_id=account.id, location="London")
        manchester = SearchProfile(account_id=account.id, location="Manchester")
        session.add_all([london, manchester])
        session.flush()

        london_listing = Listing(
            listing_id="LONDON1",
            property_url="https://www.openrent.co.uk/111111",
            search_profile_id=london.id,
        )
        manchester_listing = Listing(
            listing_id="MANCHESTER1",
            property_url="https://www.openrent.co.uk/222222",
            search_profile_id=manchester.id,
        )
        session.add_all([london_listing, manchester_listing])
        session.flush()

        london_conversation = Conversation(
            thread_id="LONDON-T",
            listing_id=london_listing.id,
            extracted_phone="07123456781",
            phone_found_at=datetime.utcnow(),
        )
        manchester_conversation = Conversation(
            thread_id="MANCHESTER-T",
            listing_id=manchester_listing.id,
            extracted_phone="07123456782",
            phone_found_at=datetime.utcnow(),
        )
        session.add_all([london_conversation, manchester_conversation])
        session.commit()
        london_conversation_id = london_conversation.id

    preview = repository.backfill_sheet_export_outbox(
        dry_run=True,
        location="london",
    )

    assert preview["matched_phone_leads"] == 1
    assert preview["eligible"] == 1
    assert preview["leads"][0]["listing_id"] == "LONDON1"

    applied = repository.backfill_sheet_export_outbox(
        dry_run=False,
        location="London",
    )

    assert applied["created"] == 1
    with db_session() as session:
        exports = session.query(LeadSheetExport).all()
        assert len(exports) == 1
        assert exports[0].conversation_id == london_conversation_id


def test_backfill_can_requeue_existing_location_exports(db_session):
    with db_session() as session:
        account = Account(email="requeue@example.com", password="", session_file="s.json")
        session.add(account)
        session.flush()
        profile = SearchProfile(account_id=account.id, location="South London")
        session.add(profile)
        session.flush()
        listing = Listing(
            listing_id="SOUTH1",
            property_url="https://www.openrent.co.uk/333333",
            search_profile_id=profile.id,
        )
        session.add(listing)
        session.flush()
        conversation = Conversation(
            thread_id="SOUTH-T",
            listing_id=listing.id,
            extracted_phone="07123456783",
            phone_found_at=datetime.utcnow(),
        )
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

    preview = repository.backfill_sheet_export_outbox(
        dry_run=True,
        location="London",
        requeue_existing=True,
    )

    assert preview["eligible"] == 0
    assert preview["already_tracked"] == 1
    assert preview["actionable"] == 1
    assert preview["leads"][0]["action"] == "requeue"

    applied = repository.backfill_sheet_export_outbox(
        dry_run=False,
        location="London",
        requeue_existing=True,
    )

    assert applied["created"] == 0
    assert applied["requeued"] == 1
    with db_session() as session:
        export = session.query(LeadSheetExport).one()
        assert export.status == "PENDING"
        assert export.exported_at is None


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


def test_dashboard_leads_include_persisted_listing_metadata_and_ids(
    db_session,
):
    captured_at = datetime.utcnow()

    with db_session() as session:
        account = Account(
            email="crm@example.com",
            password="",
            session_file="crm.json",
        )
        session.add(account)
        session.flush()
        profile = SearchProfile(
            account_id=account.id,
            location="South London",
            price_min=1500,
            price_max=2500,
            bedrooms_min=1,
            bedrooms_max=3,
        )
        session.add(profile)
        session.flush()
        listing = Listing(
            listing_id="2936562",
            property_url="https://www.openrent.co.uk/2936562",
            message_url="https://www.openrent.co.uk/messages/44552923",
            search_profile_id=profile.id,
            landlord_id=42,
            landlord_name="Jane Smith",
            property_address="Engleheart Drive, TW14",
            bedrooms=2,
            bathrooms=1,
            rent_pcm=1700,
            metadata_captured_at=captured_at,
        )
        session.add(listing)
        session.flush()
        conversation = Conversation(
            thread_id="44552923",
            listing_id=listing.id,
            extracted_phone="07123456789",
        )
        session.add(conversation)
        session.commit()

        expected = {
            "account_id": account.id,
            "search_profile_id": profile.id,
            "listing_pk": listing.id,
            "conversation_id": conversation.id,
        }

    lead = repository.get_dashboard_leads()[0]

    assert lead["conversation_id"] == expected["conversation_id"]
    assert lead["listing_pk"] == expected["listing_pk"]
    assert lead["listing_id"] == "2936562"
    assert lead["landlord_id"] == 42
    assert lead["account_id"] == expected["account_id"]
    assert lead["search_profile_id"] == expected["search_profile_id"]
    assert lead["landlord_name"] == "Jane Smith"
    assert lead["property_address"] == "Engleheart Drive, TW14"
    assert lead["bedrooms"] == 2
    assert lead["bathrooms"] == 1
    assert lead["rent_pcm"] == 1700
    assert lead["metadata_captured_at"] == captured_at


def test_metadata_backfill_candidates_require_explicit_ids_location_and_export(
    db_session,
):
    with db_session() as session:
        account = Account(email="scope@example.com", password="", session_file="scope.json")
        session.add(account)
        session.flush()
        london = SearchProfile(account_id=account.id, location="South London")
        manchester = SearchProfile(account_id=account.id, location="Manchester")
        session.add_all([london, manchester])
        session.flush()

        london_listing = Listing(
            listing_id="LONDON-1",
            property_url="https://www.openrent.co.uk/LONDON-1",
            search_profile_id=london.id,
        )
        manchester_listing = Listing(
            listing_id="MANCHESTER-1",
            property_url="https://www.openrent.co.uk/MANCHESTER-1",
            search_profile_id=manchester.id,
        )
        untracked_listing = Listing(
            listing_id="LONDON-UNTRACKED",
            property_url="https://www.openrent.co.uk/LONDON-UNTRACKED",
            search_profile_id=london.id,
        )
        session.add_all([london_listing, manchester_listing, untracked_listing])
        session.flush()

        conversations = [
            Conversation(
                thread_id="LONDON-T",
                listing_id=london_listing.id,
                extracted_phone="07111111111",
                phone_found_at=datetime.utcnow(),
            ),
            Conversation(
                thread_id="MANCHESTER-T",
                listing_id=manchester_listing.id,
                extracted_phone="07222222222",
                phone_found_at=datetime.utcnow(),
            ),
            Conversation(
                thread_id="UNTRACKED-T",
                listing_id=untracked_listing.id,
                extracted_phone="07333333333",
                phone_found_at=datetime.utcnow(),
            ),
        ]
        session.add_all(conversations)
        session.flush()
        session.add_all([
            LeadSheetExport(conversation_id=conversations[0].id, status="EXPORTED"),
            LeadSheetExport(conversation_id=conversations[1].id, status="EXPORTED"),
        ])
        session.commit()

    result = repository.get_sheet_metadata_backfill_candidates(
        ["LONDON-1", "MANCHESTER-1", "LONDON-UNTRACKED"],
        location="London",
    )

    assert result["matched_listing_ids"] == ["LONDON-1"]
    assert result["missing_listing_ids"] == [
        "MANCHESTER-1",
        "LONDON-UNTRACKED",
    ]
    assert [candidate["listing_id"] for candidate in result["candidates"]] == [
        "LONDON-1"
    ]
