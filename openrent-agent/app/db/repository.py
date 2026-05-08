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
def get_uncontacted_listings(limit=5):

    db = SessionLocal()

    listings = db.query(Listing).filter(
        Listing.message_sent == False,
        Listing.processing_failed == False
    ).limit(limit).all()

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