from datetime import datetime, timedelta
import re

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.advisor import area_intelligence
from app.advisor import recommendation_engine
from app.db.models import Account, Base, Conversation, Landlord, Listing, SearchProfile


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "area-intelligence.db"
    engine = create_engine(f"sqlite:///{db_path}")
    TestingSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
        expire_on_commit=False,
    )
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(area_intelligence, "SessionLocal", TestingSessionLocal)
    return TestingSessionLocal


def _seed_area(
    db_session,
    location="Croydon, Greater London",
    active_accounts=1,
    usable_listings=12,
    agent_listings=2,
    contacted_with_replies=5,
    contacted_with_phones=3,
):
    now = datetime.utcnow()
    email_prefix = re.sub(r"[^a-z0-9]+", "-", location.lower()).strip("-")
    with db_session() as db:
        accounts = []
        for idx in range(active_accounts):
            account = Account(
                email=f"{email_prefix}-acct-{idx}@example.com",
                password="",
                active=True,
                daily_limit=8,
            )
            db.add(account)
            db.flush()
            accounts.append(account)

        profile = SearchProfile(
            account_id=accounts[0].id,
            location=location,
            active=True,
        )
        db.add(profile)
        db.flush()

        private_landlord = Landlord(
            profile_url=f"/account/view/private-{location}",
            property_count=1,
            is_agent=False,
        )
        agent_landlord = Landlord(
            profile_url=f"/account/view/agent-{location}",
            property_count=8,
            is_agent=True,
        )
        db.add_all([private_landlord, agent_landlord])
        db.flush()

        for idx in range(usable_listings):
            db.add(
                Listing(
                    listing_id=f"{location}-usable-{idx}",
                    property_url=f"https://example.com/{location}/usable/{idx}",
                    search_profile_id=profile.id,
                    landlord_id=private_landlord.id,
                    first_seen=now - timedelta(days=idx % 6),
                )
            )

        for idx in range(agent_listings):
            db.add(
                Listing(
                    listing_id=f"{location}-agent-{idx}",
                    property_url=f"https://example.com/{location}/agent/{idx}",
                    search_profile_id=profile.id,
                    landlord_id=agent_landlord.id,
                    first_seen=now - timedelta(days=idx),
                )
            )

        for idx in range(contacted_with_replies):
            listing = Listing(
                listing_id=f"{location}-contacted-{idx}",
                property_url=f"https://example.com/{location}/contacted/{idx}",
                search_profile_id=profile.id,
                landlord_id=private_landlord.id,
                first_seen=now - timedelta(days=idx),
                contacted=True,
                message_sent=True,
                thread_id=f"thread-{location}-{idx}",
            )
            db.add(listing)
            db.flush()
            db.add(
                Conversation(
                    thread_id=f"thread-{location}-{idx}",
                    listing_id=listing.id,
                    last_processed_message="Yes, viewing is possible",
                    extracted_phone=(
                        f"07{abs(hash(email_prefix)) % 1000000:06d}{idx:03d}"
                        if idx < contacted_with_phones
                        else None
                    ),
                )
            )

        db.commit()


def test_area_metrics_calculate_supply_and_conversion(db_session):
    _seed_area(db_session)

    metrics = area_intelligence.get_area_metrics()

    assert len(metrics) == 1
    croydon = metrics[0]
    assert croydon["location"] == "Croydon, Greater London"
    assert croydon["active_profiles"] == 1
    assert croydon["active_accounts"] == 1
    assert croydon["usable_inventory"] == 12
    assert croydon["agent_listings"] == 2
    assert croydon["previously_contacted_listings"] == 5
    assert croydon["conversations"] == 5
    assert croydon["replies"] == 5
    assert croydon["phones"] == 3
    assert croydon["phone_capture_rate_pct"] == 60
    assert croydon["status"] == "maintain"


def test_area_metrics_counts_unique_active_accounts(db_session):
    with db_session() as db:
        account = Account(email="unique@example.com", password="", active=True)
        db.add(account)
        db.flush()
        db.add_all(
            [
                SearchProfile(
                    account_id=account.id,
                    location="Bexleyheath, Greater London",
                    active=True,
                ),
                SearchProfile(
                    account_id=account.id,
                    location="Bexleyheath, Greater London",
                    active=True,
                ),
            ]
        )
        db.commit()

    metrics = area_intelligence.get_area_metrics()

    assert metrics[0]["active_profiles"] == 2
    assert metrics[0]["active_accounts"] == 1


def test_area_capacity_answer_uses_measured_area_metrics(db_session):
    _seed_area(db_session, usable_listings=24, contacted_with_phones=4)

    answer = area_intelligence.answer_area_question(
        "How many SIMs do we need for Croydon, Greater London?"
    )

    assert answer is not None
    assert "**Croydon, Greater London capacity**" in answer
    assert "Usable inventory: 24 listings" in answer
    assert "SIMs justified by measured supply: 3" in answer
    assert "Proxies justified at 2 accounts/proxy: 2" in answer


def test_next_area_recommendation_prefers_expand_status(db_session):
    _seed_area(
        db_session,
        location="Croydon, Greater London",
        active_accounts=1,
        usable_listings=24,
        contacted_with_phones=4,
    )
    _seed_area(
        db_session,
        location="Lewisham, London",
        active_accounts=2,
        usable_listings=8,
        contacted_with_phones=1,
    )

    answer = area_intelligence.answer_area_question("Which area should we target next?")

    assert answer is not None
    assert "Next area recommendation: Croydon, Greater London" in answer


def test_recommendation_engine_uses_area_intelligence_before_llm(monkeypatch):
    class ExplodingClient:
        @property
        def chat(self):
            raise AssertionError("OpenAI should not be called")

    monkeypatch.setattr(
        recommendation_engine,
        "answer_area_question",
        lambda question: "deterministic area answer",
    )
    monkeypatch.setattr(recommendation_engine, "_client", ExplodingClient())

    assert (
        recommendation_engine.generate_recommendation("Which area should we target next?")
        == "deterministic area answer"
    )
