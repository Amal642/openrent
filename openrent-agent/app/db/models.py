from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    DateTime,
    Float,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import TypeDecorator

from datetime import datetime
from app.utils.crypto import decrypt, encrypt


class EncryptedString(TypeDecorator):
    """
    Transparently encrypts on write and decrypts on read.
    Stored as TEXT in the DB; legacy plaintext values are returned
    unchanged so migration can happen row-by-row without downtime.
    """
    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt(value)

Base = declarative_base()


# ---------------- LOCATIONS ----------------

class Location(Base):
    """A place the system operates in.

    `term_value` is the exact string submitted to OpenRent's search and stored
    on search_profiles.location — so it is also the key Area Intelligence uses
    to map listings to an area. The area fields below (region, radius, price /
    bedroom defaults) drive the Area Intelligence dashboard and the SIM
    allocator; `allocatable` gates whether the allocator may assign SIMs here.
    """

    __tablename__ = "locations"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    term_value = Column(String, nullable=False)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Area intelligence / allocator fields
    region = Column(String, nullable=False, default="South")
    radius_km = Column(Integer, nullable=False, default=5)
    price_min = Column(Integer, nullable=False, default=1000)
    price_max = Column(Integer, nullable=False, default=4000)
    bedrooms_min = Column(Integer, nullable=False, default=0)
    bedrooms_max = Column(Integer, nullable=False, default=4)
    allocatable = Column(Boolean, nullable=False, default=False)


# ---------------- PROXIES ----------------

class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    username = Column(String, nullable=True)
    password = Column(EncryptedString, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)

    proxy_type = Column(String, default="static")  # "static" or "rotating"

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
    password = Column(EncryptedString, nullable=False)

    initial_message = Column(Text, nullable=True)

    session_file = Column(String)

    proxy_server = Column(String, nullable=True)
    proxy_username = Column(String, nullable=True)
    proxy_password = Column(EncryptedString, nullable=True)

    daily_limit = Column(Integer, default=8)
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
    next_outreach_at = Column(DateTime, nullable=True)

    failed = Column(Boolean, default=False)
    failed_at = Column(DateTime, nullable=True)
    failure_reason = Column(Text, nullable=True)

    deleted_at = Column(DateTime, nullable=True)

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
    fail_reason = Column(String, nullable=True)

    skip_reason = Column(String, nullable=True)

    thread_id = Column(String, nullable=True)

    first_seen = Column(DateTime, default=datetime.utcnow)

    last_processed_at = Column(DateTime, nullable=True)
    processing_owner = Column(String, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
    listing_last_seen = Column(DateTime, nullable=True)
    listing_archived = Column(Boolean, default=False)

    property_address = Column(String, nullable=True)
    bedrooms = Column(Integer, nullable=True)
    bathrooms = Column(Integer, nullable=True)
    rent_pcm = Column(Integer, nullable=True)
    landlord_name = Column(String, nullable=True)
    metadata_captured_at = Column(DateTime, nullable=True)

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
    our_number_shared_at = Column(DateTime, nullable=True)

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

    last_outbound_at = Column(DateTime, nullable=True)
    follow_up_count = Column(Integer, default=0)

    viewing_requested = Column(
        Boolean,
        default=False
    )

    viewing_confirmed = Column(
        Boolean,
        default=False
    )

    viewing_confirmation_source = Column(
        String,
        nullable=True,
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

    sheet_export = relationship(
        "LeadSheetExport",
        back_populates="conversation",
        uselist=False,
        cascade="all, delete-orphan",
    )


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


class LeadSheetExport(Base):
    __tablename__ = "lead_sheet_exports"
    __table_args__ = (
        UniqueConstraint("conversation_id", name="uq_lead_sheet_export_conversation"),
    )

    id = Column(Integer, primary_key=True)
    conversation_id = Column(
        Integer,
        ForeignKey("conversations.id"),
        nullable=False,
    )

    status = Column(String, nullable=False, default="PENDING")
    attempt_count = Column(Integer, nullable=False, default=0)
    next_attempt_at = Column(DateTime, nullable=True)
    processing_started_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)

    destination_tab = Column(String, nullable=True)
    destination_row = Column(Integer, nullable=True)
    payload_hash = Column(String, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )
    exported_at = Column(DateTime, nullable=True)

    conversation = relationship("Conversation", back_populates="sheet_export")


# ---------------- WHATSAPP CONTACTS ----------------

class WhatsAppContact(Base):
    __tablename__ = "whatsapp_contacts"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String, unique=True, nullable=False, index=True)
    lid = Column(String, nullable=True, index=True)
    jid = Column(String, nullable=True)
    name = Column(String, nullable=True)
    landlord_id = Column(Integer, ForeignKey("landlords.id"), nullable=True)
    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=True)
    thread_id = Column(String, nullable=True)
    first_message = Column(Text, nullable=True)
    last_message = Column(Text, nullable=True)
    message_history = Column(Text, nullable=True)
    extracted_names = Column(Text, nullable=True)
    property_hints = Column(Text, nullable=True)
    match_status = Column(String, default="UNMATCHED")
    match_candidates = Column(Text, nullable=True)
    last_message_id = Column(String, nullable=True)
    last_ai_reply = Column(Text, nullable=True)
    last_received_at = Column(DateTime, nullable=True)
    status = Column(String, default="NEW_CONTACT")
    confidence = Column(Float, nullable=True)
    is_manual = Column(Boolean, default=False, nullable=True)
    property_address = Column(String, nullable=True)
    property_ask_count = Column(Integer, default=0, nullable=True)
    reply_scheduled_at = Column(DateTime, nullable=True)
    cancellation_sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------- APP SETTINGS (generic persisted key/value flags) ----------------

class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String, primary_key=True)
    value = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ---------------- TELEGRAM ALERTING ----------------

class AlertSubscriber(Base):
    __tablename__ = "alert_subscribers"

    id = Column(Integer, primary_key=True)
    chat_id = Column(String, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    authorized = Column(Boolean, default=False, nullable=False)
    # False once delivery keeps failing (e.g. user blocked the bot) — stop retrying.
    active = Column(Boolean, default=True, nullable=False)
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime, nullable=True)
    joined_at = Column(DateTime, default=datetime.utcnow)
    authorized_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AlertSignature(Base):
    __tablename__ = "alert_signatures"

    signature = Column(String, primary_key=True)
    source = Column(String, nullable=False)
    title = Column(String, nullable=False)
    # True while this incident is alerted and not yet reset (fire-once gate).
    active = Column(Boolean, default=True, nullable=False)
    # "auto" (proxy/whatsapp health checks, cleared on recovery) or
    # "manual" (scraper/messaging code errors, cleared via /resolve).
    resolution_mode = Column(String, default="manual", nullable=False)
    ai_explanation = Column(Text, nullable=True)
    first_seen_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)
    alert_count = Column(Integer, default=1, nullable=False)
    resolved_at = Column(DateTime, nullable=True)


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False)
    title = Column(String, nullable=False)
    detail = Column(Text, nullable=True)
    severity = Column(String, default="error", nullable=False)
    context = Column(Text, nullable=True)
    exception_type = Column(String, nullable=True)
    signature = Column(String, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    processed_at = Column(DateTime, nullable=True)
    outcome = Column(String, nullable=True)
