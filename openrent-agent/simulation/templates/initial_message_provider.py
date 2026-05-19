from abc import ABC, abstractmethod

from fastapi import HTTPException


DEFAULT_INITIAL_MESSAGE = (
    "Hi, I'm Mary, I work in IT. My husband and I really like your property "
    "and were hoping to have a quick call before booking a viewing.\n"
    "Could you please share your phone number?\n"
    "Thanks so much!"
)


class InitialMessageProvider(ABC):
    source = "unknown"

    @abstractmethod
    def get_message(self) -> str:
        raise NotImplementedError


class FixtureInitialMessageProvider(InitialMessageProvider):
    source = "fixture"

    def __init__(self, message: str | None = None):
        self.message = (message or DEFAULT_INITIAL_MESSAGE).strip()

    def get_message(self) -> str:
        return self.message


class ManualInitialMessageProvider(InitialMessageProvider):
    source = "manual"

    def __init__(self, message: str):
        self.message = (message or "").strip()

    def get_message(self) -> str:
        if not self.message:
            raise HTTPException(
                status_code=400,
                detail="Manual initial_message is required",
            )
        return self.message


class AccountInitialMessageProvider(InitialMessageProvider):
    source = "account"

    def __init__(self, account_id: int):
        self.account_id = account_id

    def get_message(self) -> str:
        from app.db.connection import SessionLocal
        from app.db.models import Account

        db = SessionLocal()
        try:
            account = db.query(Account).filter(Account.id == self.account_id).first()
            if account is None:
                raise HTTPException(status_code=404, detail="Account not found")
            message = (account.initial_message or "").strip()
            if not message:
                raise HTTPException(
                    status_code=400,
                    detail="Account initial_message is empty",
                )
            return message
        finally:
            db.close()


def build_initial_message_provider(
    *,
    source: str | None = None,
    account_id: int | None = None,
    initial_message: str | None = None,
) -> InitialMessageProvider:
    provider_source = (source or "fixture").strip().lower()
    if provider_source == "manual":
        return ManualInitialMessageProvider(initial_message or "")
    if provider_source == "account":
        if account_id is None:
            raise HTTPException(
                status_code=400,
                detail="account_id is required for account initial message source",
            )
        return AccountInitialMessageProvider(account_id)
    if provider_source == "fixture":
        return FixtureInitialMessageProvider(initial_message)
    raise HTTPException(status_code=400, detail="Unknown initial_message_source")
