"""2026-10-08: freshest-listing-first claiming, early-access unlock timing, and
the per-account daily limit variation (8-10 on the new accounts only).

Context: accounts with a local backlog (23, 24, 26) were enquiring on listings
10-27h after discovery while fresher ones sat in other accounts' queues;
enquiries in a listing's first days get more replies."""
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Account, Base, Listing, ListingOrigin, Location, SearchProfile


@pytest.fixture()
def db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    with Session() as s:
        s.add_all([
            Location(name="Lewisham", term_value="Lewisham, London", region="South"),
            Location(name="Woolwich", term_value="Woolwich, Greater London", region="South"),
            Location(name="Harrow", term_value="Harrow, London", region="North"),
        ])
        s.commit()
    return Session


def _account(s, email, location, daily_limit=8):
    acc = Account(email=email, password="", active=True, daily_limit=daily_limit)
    s.add(acc)
    s.flush()
    prof = SearchProfile(account_id=acc.id, location=location, price_min=1000, price_max=3150,
                         bedrooms_min=0, bedrooms_max=4, area=10, active=True)
    s.add(prof)
    s.flush()
    return acc.id, prof.id


def _listing(s, profile_id, key, age_hours):
    l = Listing(listing_id=key, property_url=f"https://x/{key}", search_profile_id=profile_id,
                first_seen=datetime.utcnow() - timedelta(hours=age_hours))
    s.add(l)
    s.flush()
    return l.id


# ---- freshest first ---------------------------------------------------------

def test_takes_region_listings_newer_than_own_newest_even_from_healthy_donor(db):
    with db() as s:
        me, my_prof = _account(s, "me@x", "Lewisham, London")
        donor, donor_prof = _account(s, "d@x", "Woolwich, Greater London")
        _, north_prof = _account(s, "n@x", "Harrow, London")
        _listing(s, my_prof, "own-old", age_hours=20)
        fresh = _listing(s, donor_prof, "donor-fresh", age_hours=1)
        _listing(s, donor_prof, "donor-older", age_hours=30)      # older than mine
        _listing(s, north_prof, "north-fresh", age_hours=1)       # other region
        s.commit()

    own = repository.claim_uncontacted_listings(me, "w-me", limit=20)
    newest_own = max(l.first_seen for l in own)
    got, origins = repository.claim_overflow_listings(
        me, "w-me", limit=4, freshest=True, newer_than=newest_own
    )

    assert [l.id for l in got] == [fresh]      # donor keeps only 2: keep-back ignored
    assert origins[fresh]["origin_account_id"] == donor
    with db() as s:
        assert s.get(ListingOrigin, fresh).profile_id == donor_prof


def test_nothing_taken_when_own_queue_is_freshest(db):
    with db() as s:
        me, my_prof = _account(s, "me@x", "Lewisham, London")
        _, donor_prof = _account(s, "d@x", "Woolwich, Greater London")
        _listing(s, my_prof, "own-new", age_hours=1)
        _listing(s, donor_prof, "donor-old", age_hours=5)
        s.commit()
    newest_own = max(l.first_seen for l in repository.claim_uncontacted_listings(me, "w", limit=20))
    assert repository.claim_overflow_listings(
        me, "w", limit=4, freshest=True, newer_than=newest_own
    ) == ([], {})


def test_area_stats_credit_the_finder_not_the_sender(db, monkeypatch):
    from app.advisor import area_intelligence

    monkeypatch.setattr(area_intelligence, "SessionLocal", db)
    monkeypatch.setattr(
        area_intelligence,
        "get_area_defaults",
        lambda: {"Lewisham, London": {"region": "South"}, "Woolwich, Greater London": {"region": "South"}},
    )
    with db() as s:
        me, my_prof = _account(s, "me@x", "Lewisham, London")
        _, donor_prof = _account(s, "d@x", "Woolwich, Greater London")
        moved = _listing(s, donor_prof, "found-in-woolwich", age_hours=1)
        s.commit()
    repository.claim_overflow_listings(me, "w", limit=4, freshest=True)
    with db() as s:   # sent by "me": stays on my profile
        s.get(Listing, moved).message_sent = True
        s.commit()
        assert s.get(Listing, moved).search_profile_id == my_prof

    metrics = {m.location: m for m in area_intelligence._load_area_metrics()}
    assert metrics["Woolwich, Greater London"].new_listings_7d == 1
    assert metrics["Lewisham, London"].new_listings_7d == 0


# ---- early access unlock ----------------------------------------------------

def test_early_access_retry_follows_openrent_countdown(db):
    with db() as s:
        owner, prof = _account(s, "o@x", "Lewisham, London")
        pk = _listing(s, prof, "ea", age_hours=1)
        s.commit()

    repository.mark_listing_early_access(pk, owner, unlock_in_minutes=60)
    assert repository.claim_uncontacted_listings(owner, "w", limit=5) == []

    # 71 minutes later (unlock + 10 min margin has passed) it is claimable.
    with db() as s:
        row = s.get(Listing, pk)
        row.last_processed_at -= timedelta(minutes=71)
        s.commit()
    assert [l.id for l in repository.claim_uncontacted_listings(owner, "w", limit=5)] == [pk]


def test_unlock_countdown_parsing():
    from app.openrent.messaging import parse_unlock_minutes

    assert parse_unlock_minutes("<p>Exclusive property - Unlock in 12 hours</p>") == 720
    assert parse_unlock_minutes("Unlock in 1 hour 30 minutes") == 90
    assert parse_unlock_minutes("Unlock in 45 mins") == 45
    assert parse_unlock_minutes("Unlocked: Message now") is None


# ---- daily limit variation --------------------------------------------------

def test_listed_accounts_get_8_to_10_stable_per_day(monkeypatch):
    monkeypatch.setenv("DAILY_LIMIT_VARY_ACCOUNTS", "39-45")
    monkeypatch.delenv("DAILY_LIMIT_VARY_EXTRA", raising=False)
    days = [date(2026, 10, 8) + timedelta(days=i) for i in range(60)]
    picks = [repository.daily_limit_for_day(40, 8, d) for d in days]

    assert set(picks) == {8, 9, 10}
    assert picks == [repository.daily_limit_for_day(40, 8, d) for d in days]   # stable
    same_day = {repository.daily_limit_for_day(a, 8, days[0]) for a in range(39, 46)}
    assert len(same_day) > 1                                                  # not fleet-wide


def test_unlisted_and_search_only_accounts_unchanged(monkeypatch):
    monkeypatch.setenv("DAILY_LIMIT_VARY_ACCOUNTS", "39-45")
    d = date(2026, 10, 8)
    assert repository.daily_limit_for_day(22, 8, d) == 8      # old five: flat 8
    assert repository.daily_limit_for_day(41, 0, d) == 0      # search-only stays 0
    monkeypatch.setenv("DAILY_LIMIT_VARY_ACCOUNTS", "")
    assert repository.daily_limit_for_day(41, 8, d) == 8


def test_can_send_uses_todays_limit(db, monkeypatch):
    monkeypatch.setenv("DAILY_LIMIT_VARY_ACCOUNTS", "1-99")
    with db() as s:
        acc, _ = _account(s, "v@x", "Lewisham, London")
        s.commit()
    today_limit = repository.daily_limit_for_day(acc, 8, repository.uk_now().date())
    with db() as s:
        a = s.get(Account, acc)
        a.messages_sent_today = today_limit - 1
        a.messages_sent_reset_at = datetime.utcnow()
        s.commit()
    assert repository.can_send_message(acc) is True
    repository.increment_message_count(acc)
    assert repository.can_send_message(acc) is False
