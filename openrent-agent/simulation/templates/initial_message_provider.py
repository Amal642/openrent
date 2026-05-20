from abc import ABC, abstractmethod

from fastapi import HTTPException

from simulation.conversation_designs import (
    get_conversation_design,
)


class InitialMessageProvider(ABC):
    source = "unknown"

    @abstractmethod
    def get_message(self) -> str:
        raise NotImplementedError


class FixtureInitialMessageProvider(InitialMessageProvider):
    source = "fixture"

    def __init__(
        self,
        message: str | None = None,
        conversation_design_id: str | None = None,
        persona: dict | None = None,
    ):
        design = get_conversation_design(conversation_design_id)
        self.message = (
            message.strip() if message else design.render_opening_message(persona)
        )

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
    conversation_design_id: str | None = None,
    persona: dict | None = None,
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
        return FixtureInitialMessageProvider(
            initial_message,
            conversation_design_id=conversation_design_id,
            persona=persona,
        )
    raise HTTPException(status_code=400, detail="Unknown initial_message_source")
