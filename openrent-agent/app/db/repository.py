from contextlib import contextmanager
import re
from datetime import datetime, timedelta

from app.db.connection import SessionLocal
from app.db.models import (
    Account,
    Conversation,
    Landlord,
    Listing,
    Message,
    SearchProfile,
)
from app.db.status import VIEWING_CANCELLED
from app.ai.personas import (
    get_conversation_style,
    get_persona_template,
    materialize_persona,
    normalize_conversation_style,
    select_persona,
)


@contextmanager
def session_scope():
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------- ACCOUNTS ----------------

def create_account(
    email,
    password,
    session_file,
    initial_message,
    proxy_server=None,
    proxy_username=None,
    proxy_password=None,
    mobile_number=None,
    persona_type=None,
    phone_fetching_type=None,
    message_strategy=None,
    escalation_behavior=None,
    conversation_goal=None,
    conversation_style=None,
):
    with session_scope() as db:
        account = Account(
            email=email,
            password=password,
            session_file=session_file,
            initial_message=initial_message,
            proxy_server=proxy_server,
            proxy_username=proxy_username,
            proxy_password=proxy_password,
            mobile_number=mobile_number,
            persona_type=persona_type,
            phone_fetching_type=phone_fetching_type,
            message_strategy=message_strategy,
            escalation_behavior=escalation_behavior,
            conversation_goal=conversation_goal,
            conversation_style=conversation_style,
        )

        db.add(account)
        db.commit()
        db.refresh(account)

        return account


def update_account(
    account_id,
    email=None,
    password=None,
    session_file=None,
    initial_message=None,
    proxy_server=None,
    proxy_username=None,
    proxy_password=None,
    daily_limit=None,
    active=None,
    persona_type=None,
    mobile_number=None,
    phone_fetching_type=None,
    message_strategy=None,
    escalation_behavior=None,
    conversation_goal=None,
    conversation_style=None,
):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return None

        if email is not None:
            account.email = email
        if password is not None:
            account.password = password
        if session_file is not None:
            account.session_file = session_file
        if initial_message is not None:
            account.initial_message = initial_message
        if proxy_server is not None:
            account.proxy_server = proxy_server
        if proxy_username is not None:
            account.proxy_username = proxy_username
        if proxy_password is not None:
            account.proxy_password = proxy_password
        if daily_limit is not None:
            account.daily_limit = daily_limit
        if active is not None:
            account.active = active
        if persona_type is not None:
            account.persona_type = persona_type
        if mobile_number is not None:
            account.mobile_number = mobile_number
        if phone_fetching_type is not None:
            account.phone_fetching_type = phone_fetching_type
        if message_strategy is not None:
            account.message_strategy = message_strategy
        if escalation_behavior is not None:
            account.escalation_behavior = escalation_behavior
        if conversation_goal is not None:
            account.conversation_goal = conversation_goal
        if conversation_style is not None:
            account.conversation_style = normalize_conversation_style(conversation_style)

        db.commit()

    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        return serialize_account(account) if account else None


def get_account(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        return serialize_account(account) if account else None


def _parse_generated_names(names_text):
    names = {}

    if isinstance(names_text, dict):
        return names_text

    for line in str(names_text or "").splitlines():
        match = re.match(r"\s*(husband|wife)\s*:\s*(.+?)\s*$", line, re.I)
        if match:
            names[match.group(1).lower()] = match.group(2).strip()

    words = re.findall(r"[A-Za-z][A-Za-z'-]+", str(names_text or ""))
    if "husband" not in names and words:
        names["husband"] = words[0]
    if "wife" not in names and len(words) > 1:
        names["wife"] = words[1]

    return names


def ensure_account_persona(account_or_id):
    account_id = getattr(account_or_id, "id", account_or_id)

    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return None

        template = get_persona_template(account.persona_type) if account.persona_type else None
        partner_required = bool(template and template["names"]["partner"])
        missing = any(
            getattr(account, field) in (None, "")
            for field in (
                "persona_type",
                "persona_name",
                "persona_job",
                "home_city",
                "phone_fetching_type",
                "message_strategy",
                "escalation_behavior",
                "conversation_goal",
                "conversation_style",
            )
        )
        if partner_required:
            missing = missing or any(
                getattr(account, field) in (None, "")
                for field in (
                    "persona_partner_name",
                    "persona_partner_job",
                )
            )

        if missing:
            selected = (
                materialize_persona(template, seed=f"{account.id}:{account.email}")
                if template
                else materialize_persona(
                    get_persona_template(select_persona()["persona_type"]),
                    seed=f"{account.id}:{account.email}",
                )
            )
            account.persona_type = account.persona_type or selected["persona_type"]
            account.persona_name = account.persona_name or selected["persona_name"]
            account.persona_partner_name = (
                account.persona_partner_name or selected["persona_partner_name"]
            )
            account.persona_job = account.persona_job or selected["persona_job"]
            account.persona_partner_job = (
                account.persona_partner_job or selected["persona_partner_job"]
            )
            account.home_city = account.home_city or selected["home_city"]
            account.conversation_style = (
                account.conversation_style or selected["conversation_style"]
            )
            style_config = get_conversation_style(account.conversation_style)
            account.phone_fetching_type = (
                account.phone_fetching_type
                or selected.get("phone_fetching_type")
                or style_config["phone_fetching_type"]
            )
            account.message_strategy = (
                account.message_strategy
                or selected.get("message_strategy")
                or style_config["strategy"]
            )
            account.escalation_behavior = (
                account.escalation_behavior
                or selected.get("escalation_behavior")
                or style_config["escalation_behavior"]
            )
            account.conversation_goal = (
                account.conversation_goal
                or selected.get("conversation_goal")
                or style_config["conversation_goal"]
            )
            db.commit()

        template = get_persona_template(account.persona_type) or {}
        conversation_style = normalize_conversation_style(
            account.conversation_style
            or (template.get("conversation_styles") or ["friendly_viewing"])[0]
        )
        style_config = get_conversation_style(conversation_style)

        return {
            "persona_type": account.persona_type,
            "persona_name": account.persona_name,
            "persona_partner_name": account.persona_partner_name,
            "persona_job": account.persona_job,
            "persona_partner_job": account.persona_partner_job,
            "home_city": account.home_city,
            "household_description": template.get("household_description"),
            "message_tone": template.get("message_tone"),
            "display_name": template.get("display_name"),
            "mobile_number": account.mobile_number,
            "phone_fetching_type": (
                account.phone_fetching_type
                or template.get("phone_fetching_type")
                or style_config["phone_fetching_type"]
            ),
            "message_strategy": (
                account.message_strategy
                or template.get("message_strategy")
                or style_config["strategy"]
            ),
            "escalation_behavior": (
                account.escalation_behavior
                or template.get("escalation_behavior")
                or style_config["escalation_behavior"]
            ),
            "conversation_goal": (
                account.conversation_goal
                or template.get("conversation_goal")
                or style_config["conversation_goal"]
            ),
            "conversation_style": conversation_style,
            "conversation_styles": template.get("conversation_styles") or [],
            "screening_posture": template.get("screening_posture"),
            "phone_boundary": template.get("phone_boundary"),
        }


def serialize_account(account):
    persona = ensure_account_persona(account.id)

    return {
        "id": account.id,
        "email": account.email,
        "session_file": account.session_file,
        "proxy_server": account.proxy_server,
        "proxy_username": account.proxy_username,
        "proxy_password": account.proxy_password,
        "initial_message": account.initial_message,
        "daily_limit": account.daily_limit,
        "messages_sent_today": account.messages_sent_today,
        "active": account.active,
        "created_at": account.created_at,
        "persona_name": persona["persona_name"] if persona else None,
        "persona_partner_name": persona["persona_partner_name"] if persona else None,
        "persona_job": persona["persona_job"] if persona else None,
        "persona_partner_job": persona["persona_partner_job"] if persona else None,
        "home_city": persona["home_city"] if persona else None,
        "persona_type": persona["persona_type"] if persona else None,
        "household_description": persona["household_description"] if persona else None,
        "message_tone": persona["message_tone"] if persona else None,
        "persona_label": persona["display_name"] if persona else None,
        "mobile_number": persona["mobile_number"] if persona else None,
        "phone_fetching_type": persona["phone_fetching_type"] if persona else None,
        "message_strategy": persona["message_strategy"] if persona else None,
        "escalation_behavior": persona["escalation_behavior"] if persona else None,
        "conversation_goal": persona["conversation_goal"] if persona else None,
        "conversation_style": persona["conversation_style"] if persona else None,
        "conversation_styles": persona["conversation_styles"] if persona else [],
        "screening_posture": persona.get("screening_posture") if persona else None,
        "phone_boundary": persona.get("phone_boundary") if persona else None,
        "worker_status": account.worker_status or "idle",
        "worker_last_heartbeat": account.worker_last_heartbeat,
        "worker_last_error": account.worker_last_error,
        "current_worker_phase": account.current_worker_phase or "idle",
        "last_login_at": account.last_login_at,
    }


def get_active_accounts():
    with session_scope() as db:
        accounts = db.query(Account).filter(Account.active == True).all()
        for account in accounts:
            ensure_account_persona(account.id)
        return accounts


def get_dashboard_accounts():
    with session_scope() as db:
        accounts = db.query(Account).order_by(Account.created_at.desc()).all()
        return [serialize_account(account) for account in accounts]


def update_account_worker_state(account_id, status, phase=None, error=None):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return

        account.worker_status = status
        account.worker_last_heartbeat = datetime.utcnow()
        account.current_worker_phase = phase or account.current_worker_phase
        account.worker_last_error = error
        if status in ("running", "idle"):
            account.last_login_at = account.last_login_at or datetime.utcnow()
        db.commit()


def account_stop_requested(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return True

        return account.active is False or account.worker_status == "stopping"


# ---------------- SEARCH PROFILES ----------------

def create_search_profile(
    account_id,
    location,
    price_min,
    price_max,
    bedrooms_min,
    bedrooms_max,
    area,
    pets_allowed=False
):
    with session_scope() as db:
        profile = SearchProfile(
            account_id=account_id,
            location=location,
            price_min=price_min,
            price_max=price_max,
            bedrooms_min=bedrooms_min,
            bedrooms_max=bedrooms_max,
            area=area,
            pets_allowed=pets_allowed
        )

        db.add(profile)
        db.commit()
        db.refresh(profile)

        return profile


def delete_account(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(Account.id == account_id).first()
        if not account:
            return False

        profiles = (
            db.query(SearchProfile)
            .filter(SearchProfile.account_id == account_id)
            .all()
        )

        for profile in profiles:
            listings = (
                db.query(Listing)
                .filter(Listing.search_profile_id == profile.id)
                .all()
            )
            for listing in listings:
                conversations = (
                    db.query(Conversation)
                    .filter(Conversation.listing_id == listing.id)
                    .all()
                )
                for conversation in conversations:
                    (
                        db.query(Message)
                        .filter(Message.conversation_id == conversation.id)
                        .delete(synchronize_session=False)
                    )
                    db.delete(conversation)
                db.delete(listing)
            db.delete(profile)

        db.delete(account)
        db.commit()
        return True


def get_search_profiles(account_id):
    with session_scope() as db:
        return db.query(SearchProfile).filter(
            SearchProfile.account_id == account_id,
            SearchProfile.active == True
        ).all()


# ---------------- LISTINGS ----------------

def listing_exists(listing_id):
    with session_scope() as db:
        exists = db.query(Listing).filter(
            Listing.listing_id == listing_id
        ).first()

        return exists is not None


def create_listing(
    listing_id,
    property_url,
    search_profile_id
):
    with session_scope() as db:
        listing = Listing(
            listing_id=listing_id,
            property_url=property_url,
            search_profile_id=search_profile_id
        )

        db.add(listing)
        db.commit()
        db.refresh(listing)

        return listing


def get_uncontacted_listings(
    account_id,
    limit=5
):
    with session_scope() as db:
        return (
            db.query(Listing)
            .join(
                SearchProfile,
                Listing.search_profile_id == SearchProfile.id
            )
            .filter(
                SearchProfile.account_id == account_id,
                Listing.message_sent == False,
                Listing.processing_failed == False,
                Listing.skip_reason == None,
            )
            .limit(limit)
            .all()
        )


def claim_uncontacted_listings(account_id, worker_id, limit=5, stale_minutes=30):
    stale_before = datetime.utcnow() - timedelta(minutes=stale_minutes)

    with session_scope() as db:
        listings = (
            db.query(Listing)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .filter(
                SearchProfile.account_id == account_id,
                Listing.message_sent == False,
                Listing.processing_failed == False,
                Listing.skip_reason == None,
                (
                    (Listing.processing_owner == None)
                    | (Listing.processing_started_at < stale_before)
                ),
            )
            .limit(limit)
            .all()
        )

        for listing in listings:
            listing.processing_owner = worker_id
            listing.processing_started_at = datetime.utcnow()

        db.commit()
        return listings


def release_listing_claim(listing_id, worker_id=None):
    with session_scope() as db:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()
        if not listing:
            return
        if worker_id and listing.processing_owner not in (None, worker_id):
            return
        listing.processing_owner = None
        listing.processing_started_at = None
        db.commit()


def mark_listing_contacted(
    listing_id,
    thread_id=None
):
    with session_scope() as db:
        listing = db.query(Listing).filter(
            Listing.id == listing_id
        ).first()

        if listing:
            listing.contacted = True
            listing.message_sent = True
            listing.thread_id = thread_id
            listing.last_processed_at = datetime.utcnow()
            listing.processing_owner = None
            listing.processing_started_at = None

            db.commit()


def mark_listing_failed(listing_id):
    with session_scope() as db:
        listing = db.query(Listing).filter(
            Listing.id == listing_id
        ).first()

        if listing:
            listing.processing_failed = True
            listing.last_processed_at = datetime.utcnow()
            listing.processing_owner = None
            listing.processing_started_at = None

            db.commit()

def save_message_url(
    listing_id,
    message_url
):
    with session_scope() as db:
        listing = db.query(Listing).filter(
            Listing.id == listing_id
        ).first()

        if listing:
            listing.message_url = message_url
            db.commit()


def can_send_message(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(
            Account.id == account_id
        ).first()

        if not account:
            return False

        return account.messages_sent_today < account.daily_limit


def increment_message_count(account_id):
    with session_scope() as db:
        account = db.query(Account).filter(
            Account.id == account_id
        ).first()

        if account:
            account.messages_sent_today += 1
            db.commit()


def create_conversation(
    thread_id,
    listing_id=None,
    conversation_style=None,
    landlord_attitude=None,
):
    with session_scope() as db:
        conversation = Conversation(
            thread_id=thread_id,
            listing_id=listing_id,
            conversation_stage="NEW_LEAD",
            conversation_style=normalize_conversation_style(conversation_style)
            if conversation_style else None,
            landlord_attitude=landlord_attitude or "responsive",
        )

        db.add(conversation)
        db.commit()
        db.refresh(conversation)

        return conversation


def get_or_create_conversation(thread_id, listing_id=None, conversation_style=None):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            return conversation

        conversation = Conversation(
            thread_id=thread_id,
            listing_id=listing_id,
            conversation_stage="NEW_LEAD",
            conversation_style=normalize_conversation_style(conversation_style)
            if conversation_style else None,
        )
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
        return conversation


def claim_conversation(thread_id, worker_id, stale_minutes=20):
    stale_before = datetime.utcnow() - timedelta(minutes=stale_minutes)

    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if not conversation:
            conversation = Conversation(
                thread_id=thread_id,
                conversation_stage="NEW_REPLY",
            )
            db.add(conversation)
            db.flush()

        if (
            conversation.processing_owner
            and conversation.processing_owner != worker_id
            and conversation.processing_started_at
            and conversation.processing_started_at >= stale_before
        ):
            db.rollback()
            return False

        conversation.processing_owner = worker_id
        conversation.processing_started_at = datetime.utcnow()
        db.commit()
        return True


def release_conversation_claim(thread_id, worker_id=None):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()
        if not conversation:
            return
        if worker_id and conversation.processing_owner not in (None, worker_id):
            return
        conversation.processing_owner = None
        conversation.processing_started_at = None
        db.commit()


def save_message(thread_id, direction, content, created_at=None):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if not conversation:
            conversation = Conversation(
                thread_id=thread_id,
                conversation_stage="NEW_REPLY",
            )
            db.add(conversation)
            db.flush()

        message = Message(
            conversation_id=conversation.id,
            direction=direction,
            content=content,
            created_at=created_at or datetime.utcnow(),
        )
        conversation.last_message_at = message.created_at
        db.add(message)
        db.commit()


def save_message_once(thread_id, direction, content, created_at=None):
    content = (content or "").strip()
    if not content:
        return

    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if not conversation:
            conversation = Conversation(
                thread_id=thread_id,
                conversation_stage="NEW_REPLY",
            )
            db.add(conversation)
            db.flush()

        existing = db.query(Message).filter(
            Message.conversation_id == conversation.id,
            Message.direction == direction,
            Message.content == content,
        ).first()

        if existing:
            return

        message = Message(
            conversation_id=conversation.id,
            direction=direction,
            content=content,
            created_at=created_at or datetime.utcnow(),
        )
        conversation.last_message_at = message.created_at
        db.add(message)
        db.commit()


def save_inbound_messages(thread_id, messages):
    for message in messages or []:
        if message.get("sender") != "landlord":
            continue
        save_message_once(
            thread_id,
            "inbound",
            message.get("message") or message.get("content") or "",
        )

def save_viewing_datetime(
    thread_id,
    viewing_datetime
):

    with session_scope() as db:

        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:

            conversation.viewing_datetime = (
                viewing_datetime
            )

            conversation.viewing_confirmed = True
            conversation.conversation_stage = "VIEWING_BOOKED"

            conversation.last_stage_change = (
                datetime.utcnow()
            )

            db.commit()

def mark_viewing_cancelled(
    thread_id
):

    with session_scope() as db:

        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:

            conversation.viewing_cancelled = True
            conversation.cancellation_sent_at = datetime.utcnow()

            conversation.conversation_stage = (
                VIEWING_CANCELLED
            )

            conversation.last_stage_change = (
                datetime.utcnow()
            )

            db.commit()

def mark_phone_requested(
    thread_id
):

    with session_scope() as db:

        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:

            conversation.phone_requested_at = (
                datetime.utcnow()
            )

            conversation.conversation_stage = (
                "CONTACT_REQUESTED"
            )
            conversation.last_stage_change = datetime.utcnow()

            db.commit()


def mark_phone_number_shared(thread_id):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.phone_number_shared_at = datetime.utcnow()
            db.commit()


def mark_landlord_asked_phone(thread_id):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.landlord_asked_phone_at = datetime.utcnow()
            db.commit()


def update_conversation_memory(
    thread_id,
    *,
    landlord_attitude=None,
    conversation_style=None,
):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            if landlord_attitude:
                conversation.landlord_attitude = landlord_attitude
            if conversation_style:
                conversation.conversation_style = normalize_conversation_style(
                    conversation_style
                )
            db.commit()


def update_conversation_stage(thread_id, stage):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            if conversation.conversation_stage != stage:
                conversation.conversation_stage = stage
                conversation.last_stage_change = datetime.utcnow()
            db.commit()
def update_conversation_status(
    thread_id,
    status
):
    with session_scope() as db:
        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.status = status
            db.commit()


def save_conversation_error(thread_id, reason):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.ai_error_reason = reason
            db.commit()


def save_phone_number(
    thread_id,
    phone
):
    with session_scope() as db:
        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.extracted_phone = phone
            conversation.phone_found = True
            conversation.phone_found_at = datetime.utcnow()
            conversation.status = "PHONE_ACQUIRED"
            db.commit()


def save_ai_reply(
    thread_id,
    reply
):
    with session_scope() as db:
        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.last_ai_reply = reply
            conversation.status = "AI_REPLIED"
            db.commit()


def get_conversation_messages(thread_id):
    with session_scope() as db:
        conversation = db.query(Conversation).filter(
            Conversation.thread_id == thread_id
        ).first()

        if not conversation:
            return []

        return [
            {
                "id": message.id,
                "thread_id": thread_id,
                "direction": message.direction,
                "content": message.content,
                "created_at": message.created_at,
            }
            for message in (
                db.query(Message)
                .filter(Message.conversation_id == conversation.id)
                .order_by(Message.created_at.asc(), Message.id.asc())
                .all()
            )
        ]


def mark_listing_skipped(listing_id, reason="SKIPPED"):
    with session_scope() as db:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()

        if listing:
            listing.skip_reason = reason
            listing.processing_failed = False
            listing.last_processed_at = datetime.utcnow()
            listing.processing_owner = None
            listing.processing_started_at = None
            db.commit()


def get_conversation_by_thread_id(
    thread_id
):
    with session_scope() as db:
        return db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()


def update_last_processed_message(
    thread_id,
    message
):
    with session_scope() as db:
        conversation = db.query(
            Conversation
        ).filter(
            Conversation.thread_id == thread_id
        ).first()

        if conversation:
            conversation.last_processed_message = message
            db.commit()


def phone_exists(phone):
    with session_scope() as db:
        exists = db.query(
            Conversation
        ).filter(
            Conversation.extracted_phone == phone
        ).first()

        return exists is not None


def get_or_create_landlord(profile_url):
    with session_scope() as db:
        landlord = db.query(Landlord).filter(
            Landlord.profile_url == profile_url
        ).first()

        if landlord:
            return landlord

        landlord = Landlord(profile_url=profile_url)
        db.add(landlord)
        db.commit()
        db.refresh(landlord)

        return landlord


def update_landlord_scan(profile_url, property_count, is_agent):
    with session_scope() as db:
        landlord = db.query(Landlord).filter(
            Landlord.profile_url == profile_url
        ).first()

        if landlord is None:
            landlord = Landlord(profile_url=profile_url)
            db.add(landlord)

        landlord.property_count = property_count
        landlord.is_agent = is_agent
        landlord.last_checked_at = datetime.utcnow()
        db.commit()
        db.refresh(landlord)

        return landlord


def attach_landlord_to_listing(listing_id, landlord_id):
    with session_scope() as db:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()

        if listing:
            listing.landlord_id = landlord_id
            db.commit()


def mark_listing_skipped_agent(listing_id, property_count=None):
    with session_scope() as db:
        listing = db.query(Listing).filter(Listing.id == listing_id).first()

        if listing:
            listing.skip_reason = "agent"
            listing.processing_failed = False
            listing.last_processed_at = datetime.utcnow()
            listing.processing_owner = None
            listing.processing_started_at = None
            db.commit()


def get_due_viewing_cancellations(account_id=None, hours_before=5, limit=25):
    cutoff = datetime.utcnow() + timedelta(hours=hours_before)

    with session_scope() as db:
        query = (
            db.query(Conversation, Listing, SearchProfile, Account)
            .join(Listing, Conversation.listing_id == Listing.id)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .join(Account, SearchProfile.account_id == Account.id)
            .filter(
                Conversation.viewing_datetime != None,
                Conversation.viewing_datetime <= cutoff,
                Conversation.viewing_datetime > datetime.utcnow(),
                Conversation.viewing_cancelled == False,
                Conversation.cancel_required == True,
                Conversation.cancellation_sent_at == None,
            )
            .order_by(Conversation.viewing_datetime.asc())
            .limit(limit)
        )

        if account_id is not None:
            query = query.filter(Account.id == account_id)

        return [
            {
                "thread_id": conversation.thread_id,
                "viewing_datetime": conversation.viewing_datetime,
                "property_url": listing.property_url,
                "location": search_profile.location,
                "account_id": account.id,
                "conversation_stage": conversation.conversation_stage,
            }
            for conversation, listing, search_profile, account in query.all()
        ]


def count_phones_today(account_id=None):
    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    with session_scope() as db:
        query = (
            db.query(Conversation)
            .join(Listing, Conversation.listing_id == Listing.id)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .filter(
                Conversation.extracted_phone != None,
                Conversation.phone_found_at != None,
                Conversation.phone_found_at >= start,
            )
        )

        if account_id is not None:
            query = query.filter(SearchProfile.account_id == account_id)

        return query.count()


def get_thread_property_location(thread_id):
    with session_scope() as db:
        row = (
            db.query(SearchProfile.location)
            .join(Listing, Listing.search_profile_id == SearchProfile.id)
            .join(Conversation, Conversation.listing_id == Listing.id)
            .filter(Conversation.thread_id == thread_id)
            .first()
        )

        return row[0] if row else None


def get_dashboard_leads(status=None):
    with session_scope() as db:
        query = (
            db.query(Conversation, Listing, SearchProfile, Account)
            .join(Listing, Conversation.listing_id == Listing.id)
            .join(SearchProfile, Listing.search_profile_id == SearchProfile.id)
            .join(Account, SearchProfile.account_id == Account.id)
        )

        if status and status != "ALL":
            query = query.filter(Conversation.status == status)

        rows = []

        for conversation, listing, search_profile, account in query.order_by(Conversation.created_at.desc()).all():
            persona = ensure_account_persona(account.id)
            rows.append({
                "thread_id": conversation.thread_id,
                "listing_id": listing.listing_id,
                "property_url": listing.property_url,
                "account_id": account.id,
                "account_email": account.email,
                "search_profile_id": search_profile.id,
                "location": search_profile.location,
                "price_min": search_profile.price_min,
                "price_max": search_profile.price_max,
                "bedrooms_min": search_profile.bedrooms_min,
                "bedrooms_max": search_profile.bedrooms_max,
                "area": search_profile.area,
                "pets_allowed": search_profile.pets_allowed,
                "status": conversation.status,
                "conversation_stage": conversation.conversation_stage,
                "viewing_datetime": conversation.viewing_datetime,
                "viewing_confirmed": conversation.viewing_confirmed,
                "viewing_cancelled": conversation.viewing_cancelled,
                "cancel_required": conversation.cancel_required,
                "cancellation_sent_at": conversation.cancellation_sent_at,
                "phone_requested_at": conversation.phone_requested_at,
                "phone_found_at": conversation.phone_found_at,
                "phone_number_shared_at": conversation.phone_number_shared_at,
                "landlord_asked_phone_at": conversation.landlord_asked_phone_at,
                "landlord_attitude": conversation.landlord_attitude,
                "conversation_style": (
                    conversation.conversation_style
                    or (persona["conversation_style"] if persona else None)
                ),
                "last_stage_change": conversation.last_stage_change,
                "phone": conversation.extracted_phone or "",
                "phone_number": conversation.extracted_phone or "",
                "last_processed_message": conversation.last_processed_message or "",
                "last_ai_reply": conversation.last_ai_reply or "",
                "persona_name": persona["persona_name"] if persona else account.persona_name,
                "persona_partner_name": (
                    persona["persona_partner_name"] if persona else account.persona_partner_name
                ),
                "persona_job": persona["persona_job"] if persona else account.persona_job,
                "persona_partner_job": (
                    persona["persona_partner_job"] if persona else account.persona_partner_job
                ),
                "home_city": persona["home_city"] if persona else account.home_city,
                "persona_type": persona["persona_type"] if persona else account.persona_type,
                "household_description": persona["household_description"] if persona else None,
                "message_tone": persona["message_tone"] if persona else None,
                "mobile_number": persona["mobile_number"] if persona else None,
                "phone_fetching_type": persona["phone_fetching_type"] if persona else None,
                "message_strategy": persona["message_strategy"] if persona else None,
                "escalation_behavior": persona["escalation_behavior"] if persona else None,
                "conversation_goal": persona["conversation_goal"] if persona else None,
                "created_at": conversation.created_at,
                "last_message_at": conversation.last_message_at,
            })

        return rows


def get_dashboard_search_profiles():
    with session_scope() as db:
        profiles = (
            db.query(SearchProfile, Account)
            .join(Account, SearchProfile.account_id == Account.id)
            .order_by(SearchProfile.created_at.desc())
            .all()
        )

        rows = []

        for profile, account in profiles:
            rows.append({
                "id": profile.id,
                "account_id": account.id,
                "account_email": account.email,
                "location": profile.location,
                "price_min": profile.price_min,
                "price_max": profile.price_max,
                "bedrooms_min": profile.bedrooms_min,
                "bedrooms_max": profile.bedrooms_max,
                "area": profile.area,
                "pets_allowed": profile.pets_allowed,
                "active": profile.active,
                "created_at": profile.created_at,
            })

        return rows


def get_dashboard_search_profile(profile_id):
    with session_scope() as db:
        row = (
            db.query(SearchProfile, Account)
            .join(Account, SearchProfile.account_id == Account.id)
            .filter(SearchProfile.id == profile_id)
            .first()
        )

        if not row:
            return None

        profile, account = row

        return {
            "id": profile.id,
            "account_id": account.id,
            "account_email": account.email,
            "location": profile.location,
            "price_min": profile.price_min,
            "price_max": profile.price_max,
            "bedrooms_min": profile.bedrooms_min,
            "bedrooms_max": profile.bedrooms_max,
            "area": profile.area,
            "pets_allowed": profile.pets_allowed,
            "active": profile.active,
            "created_at": profile.created_at,
        }


def update_search_profile(
    profile_id,
    account_id=None,
    location=None,
    price_min=None,
    price_max=None,
    bedrooms_min=None,
    bedrooms_max=None,
    pets_allowed=None,
    area=None,
    active=None
):
    with session_scope() as db:
        profile = db.query(SearchProfile).filter(
            SearchProfile.id == profile_id
        ).first()

        if not profile:
            return None

        if account_id is not None:
            profile.account_id = account_id
        if location is not None:
            profile.location = location
        if price_min is not None:
            profile.price_min = price_min
        if price_max is not None:
            profile.price_max = price_max
        if bedrooms_min is not None:
            profile.bedrooms_min = bedrooms_min
        if bedrooms_max is not None:
            profile.bedrooms_max = bedrooms_max
        if area is not None:
            profile.area = area
        if pets_allowed is not None:
            profile.pets_allowed = pets_allowed
        if active is not None:
            profile.active = active

        db.commit()

    return get_dashboard_search_profile(profile_id)


def deactivate_search_profile(profile_id):
    return update_search_profile(
        profile_id=profile_id,
        active=False
    )
