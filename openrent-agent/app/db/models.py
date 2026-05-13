from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy import (
    Column,
    Integer,
    String,
    Boolean,
    ForeignKey,
    DateTime,
    Text
)

from datetime import datetime

Base = declarative_base()


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

    daily_limit = Column(Integer, default=8)
    messages_sent_today = Column(Integer, default=0)

    active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # relationships
    search_profiles = relationship("SearchProfile", back_populates="account")

        

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

    closed = Column(Boolean, default=False)

    last_sender = Column(String)

    last_message_at = Column(DateTime, default=datetime.utcnow)

    created_at = Column(DateTime, default=datetime.utcnow)

    status = Column(
    String,
    default="NEW_REPLY"
    )

    extracted_phone = Column(
        String,
        nullable=True
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