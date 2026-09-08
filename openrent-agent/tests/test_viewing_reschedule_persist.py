"""save_banner_state persistence rules for reschedules.

Root cause of the silent no-show (thread 46179401): OpenRent's "viewing
confirmed" banner is NOT updated when a viewing is rescheduled in free-text, so
it keeps asserting the ORIGINAL date. save_banner_state must therefore treat the
banner as ADVANCE-ONLY (never regress a newer chat-resolved slot), while the
AI/chat source stays authoritative and re-arms the pre-viewing cancellation when
the agreed slot moves — but must never re-open an already-closed thread.
"""
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Base, Conversation
from app.utils.scheduling import uk_naive_to_utc_naive


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    db_path = tmp_path / "repo.db"
    engine = create_engine(f"sqlite:///{db_path}")
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", TestingSessionLocal)
    return TestingSessionLocal


def _make_conv(session, thread_id, viewing_dt_utc, **overrides):
    base = dict(
        thread_id=thread_id,
        viewing_datetime=viewing_dt_utc,
        viewing_confirmed=True,
        viewing_cancelled=False,
        cancellation_sent_at=None,
        handoff_completed_at=None,
        cancel_target_hours=4.0,
        conversation_stage="VIEWING_BOOKED",
        status="AI_REPLIED",
        created_at=datetime.utcnow(),
    )
    base.update(overrides)
    conv = Conversation(**base)
    session.add(conv)
    session.flush()
    return conv


def _get(session_factory, thread_id):
    with session_factory() as s:
        return (
            s.query(Conversation)
            .filter(Conversation.thread_id == thread_id)
            .first()
        )


# save_banner_state treats its `viewing_datetime` input as UK-local wall-clock.
ORIG_UK = datetime(2026, 8, 29, 10, 30)
LATER_UK = datetime(2026, 9, 5, 10, 30)


def test_stale_banner_does_not_regress_chat_resolved_slot(db_session):
    # Stored = the NEW (later) slot already resolved from chat.
    with db_session() as s:
        _make_conv(s, "t-stale", uk_naive_to_utc_naive(LATER_UK))
        s.commit()
    # OpenRent re-asserts the ORIGINAL (earlier) date via its stale banner.
    repository.save_banner_state(
        "t-stale", viewing_confirmed=True, viewing_datetime=ORIG_UK,
        confirmation_source="banner",
    )
    conv = _get(db_session, "t-stale")
    assert conv.viewing_datetime == uk_naive_to_utc_naive(LATER_UK)  # NOT regressed


def test_banner_advances_to_a_later_slot(db_session):
    with db_session() as s:
        _make_conv(s, "t-adv", uk_naive_to_utc_naive(ORIG_UK))
        s.commit()
    repository.save_banner_state(
        "t-adv", viewing_confirmed=True, viewing_datetime=LATER_UK,
        confirmation_source="banner",
    )
    conv = _get(db_session, "t-adv")
    assert conv.viewing_datetime == uk_naive_to_utc_naive(LATER_UK)  # advanced


def test_ai_source_overrides_and_rearms_cancellation(db_session):
    # A cancellation was already 'sent' for the old slot; a chat reschedule to a
    # new slot must move the date AND re-arm the cancellation (clear the flag).
    with db_session() as s:
        _make_conv(
            s, "t-ai", uk_naive_to_utc_naive(ORIG_UK),
            cancellation_sent_at=datetime(2026, 8, 29, 6, 0),
        )
        s.commit()
    repository.save_banner_state(
        "t-ai", viewing_confirmed=True, viewing_datetime=LATER_UK,
        confirmation_source="ai",
    )
    conv = _get(db_session, "t-ai")
    assert conv.viewing_datetime == uk_naive_to_utc_naive(LATER_UK)
    assert conv.cancellation_sent_at is None  # re-armed for the new slot


def test_closed_thread_is_not_reopened_on_slot_change(db_session):
    # Terminal (handed off / cancelled) threads must never be re-armed.
    sent_at = datetime(2026, 8, 29, 6, 0)
    with db_session() as s:
        _make_conv(
            s, "t-term", uk_naive_to_utc_naive(ORIG_UK),
            viewing_cancelled=True,
            handoff_completed_at=datetime(2026, 8, 29, 7, 0),
            cancellation_sent_at=sent_at,
            conversation_stage="VIEWING_CANCELLED",
        )
        s.commit()
    repository.save_banner_state(
        "t-term", viewing_confirmed=True, viewing_datetime=LATER_UK,
        confirmation_source="ai",
    )
    conv = _get(db_session, "t-term")
    assert conv.cancellation_sent_at == sent_at  # NOT re-armed


def test_first_confirmation_sets_datetime(db_session):
    # No date yet -> banner sets it (normal first booking, unchanged behaviour).
    with db_session() as s:
        _make_conv(s, "t-first", None, viewing_confirmed=False,
                   conversation_stage="VIEWING_DISCUSSION")
        s.commit()
    repository.save_banner_state(
        "t-first", viewing_confirmed=True, viewing_datetime=LATER_UK,
        confirmation_source="banner",
    )
    conv = _get(db_session, "t-first")
    assert conv.viewing_datetime == uk_naive_to_utc_naive(LATER_UK)
    assert conv.conversation_stage == "VIEWING_BOOKED"
