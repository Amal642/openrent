from app.db.connection import SessionLocal
from app.db.models import (
    Account,
    SearchProfile,
    Listing,
    Conversation,
    Message

)
from datetime import datetime


# ---------------- ACCOUNTS ----------------

def create_account(email, password, session_file, initial_message, proxy_server=None, proxy_username=None, proxy_password=None):
    db = SessionLocal()

    account = Account(
        email=email,
        password=password,
        session_file=session_file,
        initial_message=initial_message,
        proxy_server=proxy_server,
        proxy_username=proxy_username,
        proxy_password=proxy_password
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    db.close()

    return account


def get_active_accounts():
    db = SessionLocal()

    accounts = db.query(Account).filter(Account.active == True).all()

    db.close()

    return accounts


# ---------------- SEARCH PROFILES ----------------

def create_search_profile(
    account_id,
    location,
    price_min,
    price_max,
    bedrooms_min,
    bedrooms_max,
    pets_allowed=False
):
    db = SessionLocal()

    profile = SearchProfile(
        account_id=account_id,
        location=location,
        price_min=price_min,
        price_max=price_max,
        bedrooms_min=bedrooms_min,
        bedrooms_max=bedrooms_max,
        pets_allowed=pets_allowed
    )

    db.add(profile)
    db.commit()
    db.refresh(profile)

    db.close()

    return profile


def get_search_profiles(account_id):
    db = SessionLocal()

    profiles = db.query(SearchProfile).filter(
        SearchProfile.account_id == account_id,
        SearchProfile.active == True
    ).all()

    db.close()

    return profiles


# ---------------- LISTINGS ----------------

def listing_exists(listing_id):
    db = SessionLocal()

    exists = db.query(Listing).filter(
        Listing.listing_id == listing_id
    ).first()

    db.close()

    return exists is not None


def create_listing(
    listing_id,
    property_url,
    search_profile_id
):
    db = SessionLocal()

    listing = Listing(
        listing_id=listing_id,
        property_url=property_url,
        search_profile_id=search_profile_id
    )

    db.add(listing)
    db.commit()
    db.refresh(listing)

    db.close()

    return listing
def get_uncontacted_listings(
    account_id,
    limit=5
):

    db = SessionLocal()

    listings = (

        db.query(Listing)

        .join(
            SearchProfile,
            Listing.search_profile_id
            ==
            SearchProfile.id
        )

        .filter(

            SearchProfile.account_id
            ==
            account_id,

            Listing.message_sent
            ==
            False,

            Listing.processing_failed
            ==
            False
        )

        .limit(limit)

        .all()
    )

    db.close()

    return listings
def mark_listing_contacted(
    listing_id,
    thread_id=None
):

    db = SessionLocal()

    listing = db.query(Listing).filter(
        Listing.id == listing_id
    ).first()

    if listing:
        listing.contacted = True
        listing.message_sent = True
        listing.thread_id = thread_id
        listing.last_processed_at = datetime.utcnow()

        db.commit()

    db.close()
def mark_listing_failed(listing_id):

    db = SessionLocal()

    listing = db.query(Listing).filter(
        Listing.id == listing_id
    ).first()

    if listing:
        listing.processing_failed = True
        listing.last_processed_at = datetime.utcnow()

        db.commit()

    db.close()
def save_message_url(
    listing_id,
    message_url
):

    db = SessionLocal()

    listing = db.query(Listing).filter(
        Listing.id == listing_id
    ).first()

    if listing:
        listing.message_url = message_url
        db.commit()

    db.close()
def can_send_message(account_id):

    db = SessionLocal()

    account = db.query(Account).filter(
        Account.id == account_id
    ).first()

    if not account:
        db.close()
        return False

    allowed = (
        account.messages_sent_today <
        account.daily_limit
    )

    db.close()

    return allowed
def increment_message_count(account_id):

    db = SessionLocal()

    account = db.query(Account).filter(
        Account.id == account_id
    ).first()

    if account:
        account.messages_sent_today += 1
        db.commit()

    db.close()
def create_conversation(
    thread_id,
    listing_id
):

    db = SessionLocal()

    conversation = Conversation(
        thread_id=thread_id,
        listing_id=listing_id
    )

    db.add(conversation)

    db.commit()

    db.refresh(conversation)

    db.close()

    return conversation

def update_conversation_status(
    thread_id,
    status
):

    db = SessionLocal()

    conversation = db.query(
        Conversation
    ).filter(
        Conversation.thread_id == thread_id
    ).first()

    if conversation:

        conversation.status = status

        db.commit()

    db.close()
def save_conversation_error(thread_id, reason):
    db = SessionLocal()
    conversation = db.query(Conversation).filter(
        Conversation.thread_id == thread_id
    ).first()

    if conversation:
        conversation.ai_error_reason = reason
        db.commit()

    db.close()


def save_phone_number(
    thread_id,
    phone
):

    db = SessionLocal()

    conversation = db.query(
        Conversation
    ).filter(
        Conversation.thread_id == thread_id
    ).first()

    if conversation:

        conversation.extracted_phone = phone

        conversation.status = "PHONE_ACQUIRED"

        db.commit()

    db.close()

def save_ai_reply(
    thread_id,
    reply
):

    db = SessionLocal()

    conversation = db.query(
        Conversation
    ).filter(
        Conversation.thread_id == thread_id
    ).first()

    if conversation:

        conversation.last_ai_reply = reply

        conversation.status = "AI_REPLIED"

        db.commit()

    db.close()

def mark_listing_skipped(listing_id, reason="SKIPPED"):
    db = SessionLocal()
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if listing:
        listing.skip_reason = reason
        listing.processing_failed = True
        db.commit()
    db.close()

def get_conversation_by_thread_id(
    thread_id
):

    db = SessionLocal()

    conversation = db.query(
        Conversation
    ).filter(
        Conversation.thread_id == thread_id
    ).first()

    db.close()

    return conversation

def update_last_processed_message(
    thread_id,
    message
):

    db = SessionLocal()

    conversation = db.query(
        Conversation
    ).filter(
        Conversation.thread_id == thread_id
    ).first()

    if conversation:

        conversation.last_processed_message = message

        db.commit()

    db.close()

def phone_exists(phone):

    db = SessionLocal()

    exists = db.query(
        Conversation
    ).filter(
        Conversation.extracted_phone == phone
    ).first()

    db.close()

    return exists is not None

def get_or_create_landlord(profile_url):
    db = SessionLocal()
    landlord = db.query(Landlord).filter(Landlord.profile_url == profile_url).first()
    if landlord:
        db.close()
        return landlord

    landlord = Landlord(profile_url=profile_url)
    db.add(landlord)
    db.commit()
    db.refresh(landlord)
    db.close()
    return landlord


def update_landlord_scan(profile_url, property_count, is_agent):
    db = SessionLocal()
    landlord = db.query(Landlord).filter(Landlord.profile_url == profile_url).first()
    if landlord is None:
        landlord = Landlord(profile_url=profile_url)
        db.add(landlord)

    landlord.property_count = property_count
    landlord.is_agent = is_agent
    landlord.last_checked_at = datetime.utcnow()
    db.commit()
    db.refresh(landlord)
    db.close()
    return landlord


def attach_landlord_to_listing(listing_id, landlord_id):
    db = SessionLocal()
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if listing:
        listing.landlord_id = landlord_id
        db.commit()
    db.close()


def mark_listing_skipped_agent(listing_id, property_count=None):
    db = SessionLocal()
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if listing:
        listing.skip_reason = "agent"
        listing.processing_failed = True
        listing.last_processed_at = datetime.utcnow()
        db.commit()
    db.close()

def get_dashboard_leads(status=None):
    db = SessionLocal()

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
            "pets_allowed": search_profile.pets_allowed,
            "status": conversation.status,
            "phone": conversation.extracted_phone or "",
            "last_processed_message": conversation.last_processed_message or "",
            "last_ai_reply": conversation.last_ai_reply or "",
            "created_at": conversation.created_at,
            "last_message_at": conversation.last_message_at,
        })

    db.close()
    return rows


def get_dashboard_search_profiles():
    db = SessionLocal()

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
            "pets_allowed": profile.pets_allowed,
            "active": profile.active,
            "created_at": profile.created_at,
        })

    db.close()
    return rows


def get_dashboard_search_profile(profile_id):
    db = SessionLocal()

    row = (
        db.query(SearchProfile, Account)
        .join(Account, SearchProfile.account_id == Account.id)
        .filter(SearchProfile.id == profile_id)
        .first()
    )

    if not row:
        db.close()
        return None

    profile, account = row

    result = {
        "id": profile.id,
        "account_id": account.id,
        "account_email": account.email,
        "location": profile.location,
        "price_min": profile.price_min,
        "price_max": profile.price_max,
        "bedrooms_min": profile.bedrooms_min,
        "bedrooms_max": profile.bedrooms_max,
        "pets_allowed": profile.pets_allowed,
        "active": profile.active,
        "created_at": profile.created_at,
    }

    db.close()
    return result


def update_search_profile(
    profile_id,
    account_id=None,
    location=None,
    price_min=None,
    price_max=None,
    bedrooms_min=None,
    bedrooms_max=None,
    pets_allowed=None,
    active=None
):
    db = SessionLocal()

    profile = db.query(SearchProfile).filter(
        SearchProfile.id == profile_id
    ).first()

    if not profile:
        db.close()
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
    if pets_allowed is not None:
        profile.pets_allowed = pets_allowed
    if active is not None:
        profile.active = active

    db.commit()
    db.close()

    return get_dashboard_search_profile(profile_id)


def deactivate_search_profile(profile_id):
    return update_search_profile(
        profile_id=profile_id,
        active=False
    )
