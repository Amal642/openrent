"""save_message_once must treat OpenRent's retro-redaction of an old landlord
message ("07911 123456" -> "(Number Removed)") as an edit, not a new message.
On 2026-09-26 OpenRent re-redacted old threads and 221 phantom inbound rows
were stored, inflating inbound counts and bumping last_message_at.
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import repository
from app.db.models import Base, Conversation, Message


@pytest.fixture()
def db_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'msg.db'}")
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    monkeypatch.setattr(repository, "SessionLocal", Session)
    return Session


def _inbound(Session, thread_id="T1"):
    with Session() as s:
        conv = s.query(Conversation).filter_by(thread_id=thread_id).one()
        rows = s.query(Message).filter_by(conversation_id=conv.id, direction="inbound").all()
        return [r.content for r in rows], conv.last_message_at


def test_redacted_edit_of_existing_message_is_not_stored_again(db_session):
    repository.save_message_once("T1", "inbound", "Sure, call me on 07911 123456 any time")
    _, before = _inbound(db_session)
    repository.save_message_once("T1", "inbound", "Sure, call me on (Number Removed) any time")
    contents, after = _inbound(db_session)
    assert contents == ["Sure, call me on 07911 123456 any time"]
    assert after == before, "an edit must not bump last_message_at"


def test_redaction_key_ignores_spacing_and_number_format():
    a = repository._redaction_key("My number is +44 7911-123-456, thanks")
    b = repository._redaction_key("My number is (Number Removed), thanks")
    assert a == b


def test_genuinely_new_redacted_message_is_stored(db_session):
    repository.save_message_once("T1", "inbound", "Hi, is Saturday OK?")
    repository.save_message_once("T1", "inbound", "My (Number Removed)")
    contents, _ = _inbound(db_session)
    assert contents == ["Hi, is Saturday OK?", "My (Number Removed)"]


def test_normal_new_messages_still_stored(db_session):
    repository.save_message_once("T1", "inbound", "my number is 07911 123456")
    repository.save_message_once("T1", "inbound", "sorry, use 07922 654321 instead")
    contents, _ = _inbound(db_session)
    assert len(contents) == 2


def test_exact_duplicate_still_ignored(db_session):
    repository.save_message_once("T1", "inbound", "Hello")
    repository.save_message_once("T1", "inbound", "Hello")
    contents, _ = _inbound(db_session)
    assert contents == ["Hello"]


def test_outbound_messages_unaffected(db_session):
    repository.save_message_once("T1", "outbound", "Could I get your number?")
    repository.save_message_once("T1", "outbound", "Thanks (Number Removed)")
    with db_session() as s:
        assert s.query(Message).filter_by(direction="outbound").count() == 2
