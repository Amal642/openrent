import sys
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from simulation.templates.initial_message_provider import (
    AccountInitialMessageProvider,
    FixtureInitialMessageProvider,
    ManualInitialMessageProvider,
)


def test_fixture_initial_message_provider_returns_deterministic_message():
    provider = FixtureInitialMessageProvider()

    assert "arrange a viewing" in provider.get_message()
    assert "phone number" not in provider.get_message()
    assert provider.source == "fixture"


def test_manual_initial_message_provider_returns_exact_message():
    provider = ManualInitialMessageProvider("Hello from manual input.")

    assert provider.get_message() == "Hello from manual input."
    assert provider.source == "manual"


def test_account_initial_message_provider_loads_account_template(monkeypatch):
    fake_account_model = type("FakeAccount", (), {"id": "id"})
    fake_session = SimpleNamespace(
        query=lambda model: SimpleNamespace(
            filter=lambda *_args, **_kwargs: SimpleNamespace(
                first=lambda: SimpleNamespace(initial_message="Stored opener")
            )
        ),
        close=lambda: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.db.connection",
        SimpleNamespace(SessionLocal=lambda: fake_session),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.db.models",
        SimpleNamespace(Account=fake_account_model),
    )

    provider = AccountInitialMessageProvider(account_id=7)

    assert provider.get_message() == "Stored opener"
    assert provider.source == "account"


def test_account_initial_message_provider_fails_when_account_missing(monkeypatch):
    fake_account_model = type("FakeAccount", (), {"id": "id"})
    fake_session = SimpleNamespace(
        query=lambda model: SimpleNamespace(
            filter=lambda *_args, **_kwargs: SimpleNamespace(first=lambda: None)
        ),
        close=lambda: None,
    )
    monkeypatch.setitem(
        sys.modules,
        "app.db.connection",
        SimpleNamespace(SessionLocal=lambda: fake_session),
    )
    monkeypatch.setitem(
        sys.modules,
        "app.db.models",
        SimpleNamespace(Account=fake_account_model),
    )

    provider = AccountInitialMessageProvider(account_id=99)

    with pytest.raises(HTTPException) as error:
        provider.get_message()

    assert error.value.status_code == 404
