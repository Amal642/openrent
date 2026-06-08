from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    DateTime,
    Float,
    Text
)

from datetime import datetime

Base = declarative_base()


# ---------------- LOCATIONS ----------------

class Location(Base):
    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    term_value = Column(String, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ---------------- PROXIES ----------------

class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    password = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    # Future-ready fields (nullable, not enforced yet)
    health_status = Column(String, nullable=True)
    last_check_at = Column(DateTime, nullable=True)
    country = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    failure_count = Column(Integer, default=0)

    accounts = relationship("Account", back_populates="proxy")


# ---------------- ACCOUNTS ----------------

class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True)

    email = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)

    initial_message = Column(Text, nullable=True)

    session_file = Column(String)

    proxy_server = Column(String, nullable=True)
    proxy_username = Column(String, nullable=True)
    proxy_password = Column(String, nullable=True)

    daily_limit = Column(Integer, default=5)
    messages_sent_today = Column(Integer, default=0)
    messages_sent_reset_at = Column(DateTime, nullable=True)

    active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    persona_name = Column(String, nullable=True)
    persona_partner_name = Column(String, nullable=True)
    persona_job = Column(String, nullable=True)
    persona_partner_job = Column(String, nullable=True)
    home_city = Column(String, nullable=True)
    persona_type = Column(String, nullable=True)
    mobile_number = Column(String, nullable=True)
    phone_fetching_type = Column(String, nullable=True)
    message_strategy = Column(String, nullable=True)
    escalation_behavior = Column(String, nullable=True)
    conversation_goal = Column(String, nullable=True)
    conversation_style = Column(String, nullable=True)

    worker_status = Column(String, default="idle")
    worker_job_id = Column(String, nullable=True)
    worker_started_at = Column(DateTime, nullable=True)
    worker_last_heartbeat = Column(DateTime, nullable=True)
    worker_error = Column(Text, nullable=True)
    worker_last_error = Column(Text, nullable=True)
    worker_last_completed_at = Column(DateTime, nullable=True)
    current_worker_phase = Column(String, default="idle")
    last_login_at = Column(DateTime, nullable=True)
    session_status = Column(String, default="expired")
    session_last_checked = Column(DateTime, nullable=True)
    session_last_error = Column(Text, nullable=True)
    session_auth_failures = Column(Integer, default=0)
    session_captcha_triggers = Column(Integer, default=0)
    proxy_status = Column(String, default="unknown")
    proxy_ip = Column(String, nullable=True)
    proxy_latency = Column(Float, nullable=True)
    proxy_last_checked = Column(DateTime, nullable=True)
    proxy_last_error = Column(Text, nullable=True)
    proxy_failures = Column(Integer, default=0)
    retry_count = Column(Integer, default=0)
    retry_limit = Column(Integer, default=3)
    retry_reason = Column(Text, nullable=True)
    retry_next_at = Column(DateTime, nullable=True)
    last_exception = Column(Text, nullable=True)
    permanently_failed = Column(Boolean, default=False)

    listings_last_scraped_at = Column(DateTime, nullable=True)
    cooldown_until = Column(DateTime, nullable=True)

    failed = Column(Boolean, default=False)
    failed_at = Column(DateTime, nullable=True)
    failure_reason = Column(Text, nullable=True)

    proxy_id = Column(Integer, ForeignKey("proxies.id"), nullable=True)

    # relationships
    search_profiles = relationship("SearchProfile", back_populates="account")
    proxy = relationship("Proxy", back_populates="accounts")

        

# ---------------- SEARCH PROFILES ----------------

class SearchProfile(Base):
    __tablename__ = "search_profiles"

    id = Column(Integer, primary_key=True)

    account_id = Column(Integer, ForeignKey("accounts.id"))

    location = Column(String, nullable=False)

    price_min = Column(Integer)
    price_max = Column(Integer)

    bedrooms_min = Column(Integer)
    bedrooms_max = Column(Integer)

    area = Column(Integer)  

    pets_allowed = Column(Boolean, default=False)

    active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    account = relationship("Account", back_populates="search_profiles")

    listings = relationship("Listing", back_populates="search_profile")


# ---------------- LISTINGS ----------------

class Listing(Base):
    __tablename__ = "listings"

    id = Column(Integer, primary_key=True)

    listing_id = Column(String, unique=True, nullable=False)

    property_url = Column(String, nullable=False)

    search_profile_id = Column(Integer, ForeignKey("search_profiles.id"))

    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=True)


    message_url = Column(String, nullable=True)

    contacted = Column(Boolean, default=False)

    message_sent = Column(Boolean, default=False)

    processing_failed = Column(Boolean, default=False)

    skip_reason = Column(String, nullable=True)

    thread_id = Column(String, nullable=True)

    first_seen = Column(DateTime, default=datetime.utcnow)

    last_processed_at = Column(DateTime, nullable=True)
    processing_owner = Column(String, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
    listing_last_seen = Column(DateTime, nullable=True)
    listing_archived = Column(Boolean, default=False)
    # relationships
    search_profile = relationship("SearchProfile", back_populates="listings")

    conversations = relationship("Conversation", back_populates="listing")

    landlord = relationship("Landlord", back_populates="listings")


# ---------------- CONVERSATIONS ----------------

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True)

    thread_id = Column(String, unique=True)

    listing_id = Column(Integer, ForeignKey("listings.id"))

    phone_found = Column(Boolean, default=False)

    extracted_phone = Column(String, unique=True, nullable=True)
    phone_found_at = Column(DateTime, nullable=True)
    phone_number_shared_at = Column(DateTime, nullable=True)
    landlord_asked_phone_at = Column(DateTime, nullable=True)
    handoff_completed_at = Column(DateTime, nullable=True)

    closed = Column(Boolean, default=False)

    last_sender = Column(String)

    last_message_at = Column(DateTime, default=datetime.utcnow)

    created_at = Column(DateTime, default=datetime.utcnow)

    status = Column(
    String,
    default="NEW_REPLY"
    )

    last_ai_reply = Column(
        Text,
        nullable=True
    )
    last_processed_message = Column(
    Text,
    nullable=True
    )
    
    ai_error_reason = Column(Text, nullable=True)

    conversation_stage = Column(
    String,
    default="NEW_LEAD"
    )

    viewing_datetime = Column(
        DateTime,
        nullable=True
    )

    last_stage_change = Column(
        DateTime,
        default=datetime.utcnow
    )

    phone_requested_at = Column(
        DateTime,
        nullable=True
    )

    viewing_requested = Column(
        Boolean,
        default=False
    )

    viewing_confirmed = Column(
        Boolean,
        default=False
    )

    viewing_cancelled = Column(
        Boolean,
        default=False
    )

    cancel_required = Column(
    Boolean,
    default=True
    )

    cancellation_sent_at = Column(
        DateTime,
        nullable=True
    )

    cancel_target_hours = Column(
        Float,
        nullable=True
    )

    processing_owner = Column(String, nullable=True)

    processing_started_at = Column(
        DateTime,
        nullable=True
    )

    landlord_attitude = Column(String, default="responsive")

    conversation_style = Column(String, nullable=True)

    travel_city = Column(String, nullable=True)

    # relationships
    listing = relationship("Listing", back_populates="conversations")

    messages = relationship("Message", back_populates="conversation")


# ---------------- MESSAGES ----------------

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)

    conversation_id = Column(Integer, ForeignKey("conversations.id"))

    direction = Column(String)  # inbound / outbound

    content = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    conversation = relationship("Conversation", back_populates="messages")

class Landlord(Base):
    __tablename__ = "landlords"

    id = Column(Integer, primary_key=True)
    profile_url = Column(String, unique=True, nullable=False)
    property_count = Column(Integer, default=0)
    is_agent = Column(Boolean, default=False)
    last_checked_at = Column(DateTime, default=datetime.utcnow)

    listings = relationship("Listing", back_populates="landlord")
