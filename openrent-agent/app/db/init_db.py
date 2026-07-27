from sqlalchemy import inspect, text

from app.db.connection import engine
from app.db.models import Base


REQUIRED_COLUMNS = {
    "proxies": {
        "health_status":  "VARCHAR",
        "last_check_at":  "TIMESTAMP",
        "country":        "VARCHAR",
        "provider":       "VARCHAR",
        "failure_count":  "INTEGER DEFAULT 0",
        "proxy_type":     "VARCHAR DEFAULT 'static'",
    },

    "accounts": {
        "persona_name": "VARCHAR",
        "persona_partner_name": "VARCHAR",
        "persona_job": "VARCHAR",
        "persona_partner_job": "VARCHAR",
        "home_city": "VARCHAR",
        "persona_type": "VARCHAR",
        "mobile_number": "VARCHAR",
        "phone_fetching_type": "VARCHAR",
        "message_strategy": "VARCHAR",
        "escalation_behavior": "VARCHAR",
        "conversation_goal": "VARCHAR",
        "conversation_style": "VARCHAR",

        "worker_status": "VARCHAR DEFAULT 'idle'",
        "worker_job_id": "VARCHAR",
        "worker_started_at": "TIMESTAMP",
        "worker_last_heartbeat": "TIMESTAMP",
        "worker_error": "TEXT",
        "worker_last_error": "TEXT",
        "worker_last_completed_at": "TIMESTAMP",
        "current_worker_phase": "VARCHAR DEFAULT 'idle'",

        "last_login_at": "TIMESTAMP",

        "session_status": "VARCHAR DEFAULT 'expired'",
        "session_last_checked": "TIMESTAMP",
        "session_last_error": "TEXT",
        "session_auth_failures": "INTEGER DEFAULT 0",
        "session_captcha_triggers": "INTEGER DEFAULT 0",

        "proxy_status": "VARCHAR DEFAULT 'unknown'",
        "proxy_ip": "VARCHAR",
        "proxy_latency": "FLOAT",
        "proxy_last_checked": "TIMESTAMP",
        "proxy_last_error": "TEXT",
        "proxy_failures": "INTEGER DEFAULT 0",

        "retry_count": "INTEGER DEFAULT 0",
        "retry_limit": "INTEGER DEFAULT 3",
        "retry_reason": "TEXT",
        "retry_next_at": "TIMESTAMP",

        "last_exception": "TEXT",
        "permanently_failed": "BOOLEAN DEFAULT FALSE",

        "proxy_server": "VARCHAR",
        "proxy_username": "VARCHAR",
        "proxy_password": "VARCHAR",

        "messages_sent_reset_at": "TIMESTAMP",
        "listings_last_scraped_at": "TIMESTAMP",
        "proxy_id": "INTEGER",
        "cooldown_until": "TIMESTAMP",
        "next_outreach_at": "TIMESTAMP",

        "failed": "BOOLEAN DEFAULT FALSE",
        "failed_at": "TIMESTAMP",
        "failure_reason": "TEXT",

        "deleted_at": "TIMESTAMP",
    },

    "listings": {
        "processing_owner": "VARCHAR",
        "processing_started_at": "TIMESTAMP",
        "listing_last_seen": "TIMESTAMP",
        "listing_archived": "BOOLEAN DEFAULT FALSE",
        "property_address": "VARCHAR",
        "bedrooms": "INTEGER",
        "bathrooms": "INTEGER",
        "rent_pcm": "INTEGER",
        "landlord_name": "VARCHAR",
        "metadata_captured_at": "TIMESTAMP",
        "fail_reason": "TEXT",
    },

    "whatsapp_contacts": {
        "lid": "VARCHAR",
        "jid": "VARCHAR",
        "name": "VARCHAR",
        "landlord_id": "INTEGER",
        "listing_id": "INTEGER",
        "thread_id": "VARCHAR",
        "first_message": "TEXT",
        "last_message": "TEXT",
        "message_history": "TEXT",
        "extracted_names": "TEXT",
        "property_hints": "TEXT",
        "match_status": "VARCHAR DEFAULT 'UNMATCHED'",
        "match_candidates": "TEXT",
        "last_message_id": "VARCHAR",
        "last_ai_reply": "TEXT",
        "last_received_at": "TIMESTAMP",
        "status": "VARCHAR DEFAULT 'NEW_CONTACT'",
        "confidence": "FLOAT",
        "is_manual": "BOOLEAN DEFAULT FALSE",
        "property_address": "VARCHAR",
        "property_ask_count": "INTEGER DEFAULT 0",
        "reply_scheduled_at": "TIMESTAMP",
        "cancellation_sent_at": "TIMESTAMP",
        "created_at": "TIMESTAMP",
        "updated_at": "TIMESTAMP",
    },

    "conversations": {
        "ai_error_reason": "TEXT",

        "conversation_stage": "VARCHAR DEFAULT 'NEW_LEAD'",

        "viewing_datetime": "TIMESTAMP",

        "last_stage_change": "TIMESTAMP",

        "phone_requested_at": "TIMESTAMP",
        "phone_found_at": "TIMESTAMP",
        "phone_number_shared_at": "TIMESTAMP",
        "landlord_asked_phone_at": "TIMESTAMP",
        "handoff_completed_at": "TIMESTAMP",

        "landlord_attitude": "VARCHAR DEFAULT 'responsive'",
        "conversation_style": "VARCHAR",

        "viewing_requested": "BOOLEAN DEFAULT FALSE",
        "viewing_confirmed": "BOOLEAN DEFAULT FALSE",
        "viewing_confirmation_source": "VARCHAR",
        "viewing_cancelled": "BOOLEAN DEFAULT FALSE",

        "cancel_required": "BOOLEAN DEFAULT TRUE",

        "cancellation_sent_at": "TIMESTAMP",

        "cancel_target_hours": "FLOAT",

        "processing_owner": "VARCHAR",
        "processing_started_at": "TIMESTAMP",

        "travel_city": "VARCHAR",

        "last_outbound_at": "TIMESTAMP",
        "follow_up_count": "INTEGER DEFAULT 0",
        "our_number_shared_at": "TIMESTAMP",
    },

    "locations": {
        "region": "VARCHAR DEFAULT 'South'",
        "radius_km": "INTEGER DEFAULT 5",
        "price_min": "INTEGER DEFAULT 1000",
        "price_max": "INTEGER DEFAULT 4000",
        "bedrooms_min": "INTEGER DEFAULT 0",
        "bedrooms_max": "INTEGER DEFAULT 4",
        "allocatable": "BOOLEAN DEFAULT FALSE",
    },
}


def apply_schema_updates():
    inspector = inspect(engine)

    with engine.begin() as connection:
        for table_name, columns in REQUIRED_COLUMNS.items():

            existing_columns = {
                column["name"].lower()
                for column in inspector.get_columns(table_name)
            }

            for column_name, column_type in columns.items():

                if column_name.lower() in existing_columns:
                    continue

                query = (
                    f"ALTER TABLE {table_name} "
                    f"ADD COLUMN {column_name} {column_type}"
                )

                print(f"Applying schema update: {query}")

                connection.execute(text(query))


def _migrate_account_proxies():
    """
    One-time migration: lift legacy per-account proxy credentials into
    shared Proxy records and set account.proxy_id.
    Idempotent — skips accounts that already have a proxy_id.
    """
    from app.db.connection import SessionLocal
    from app.db.models import Account, Proxy

    db = SessionLocal()
    try:
        accounts = (
            db.query(Account)
            .filter(Account.proxy_server != None, Account.proxy_id == None)
            .all()
        )

        proxy_counter = db.query(Proxy).count()

        for account in accounts:
            proxy_counter += 1
            proxy = Proxy(
                name=f"Proxy {proxy_counter}",
                host=account.proxy_server or "",
                port=0,
                username=account.proxy_username,
                password=account.proxy_password,
                is_active=True,
            )
            db.add(proxy)
            db.flush()
            account.proxy_id = proxy.id

        if accounts:
            db.commit()
            print(f"Migrated {len(accounts)} account proxy credential(s) to proxy records")
    except Exception as exc:
        db.rollback()
        print(f"Proxy migration skipped (will retry next start): {exc}")
    finally:
        db.close()


def validate_schema_or_die():
    """
    Defense in depth against REQUIRED_COLUMNS drift: introspect every column
    declared on every SQLAlchemy model (the single source of truth) and
    compare against what actually exists in the live database. If a model
    column was added but never registered in REQUIRED_COLUMNS above (exactly
    what happened when next_outreach_at/last_outbound_at/follow_up_count were
    added to models.py but not to this file), fail fast at startup with a
    clear error instead of letting the app come up and crash later deep
    inside a worker run with a cryptic psycopg2.UndefinedColumn traceback.
    """
    inspector = inspect(engine)
    missing = []

    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            missing.append(f"{table.name} (entire table missing)")
            continue

        existing_columns = {
            column["name"].lower()
            for column in inspector.get_columns(table.name)
        }

        for column in table.columns:
            if column.name.lower() not in existing_columns:
                missing.append(f"{table.name}.{column.name}")

    if missing:
        raise RuntimeError(
            "Database schema is missing columns required by the current "
            "SQLAlchemy models — the app cannot start safely:\n  "
            + "\n  ".join(missing)
            + "\n\nAdd the missing column(s) to REQUIRED_COLUMNS in "
            "app/db/init_db.py (or run the matching file in "
            "app/db/migrations/), then restart."
        )


def _migrate_daily_limit_to_8():
    """One-time migration: accounts still on the old default of 5 are bumped to 8."""
    from app.db.connection import SessionLocal
    from app.db.models import Account

    db = SessionLocal()
    try:
        updated = (
            db.query(Account)
            .filter(Account.daily_limit == 5)
            .update({"daily_limit": 8}, synchronize_session=False)
        )
        if updated:
            db.commit()
            print(f"Migrated {updated} account(s) daily_limit 5 → 8")
    except Exception as exc:
        db.rollback()
        print(f"daily_limit migration skipped: {exc}")
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)

    apply_schema_updates()
    _migrate_account_proxies()
    _migrate_daily_limit_to_8()
    _migrate_area_configs_into_locations()
    _seed_allocatable_locations()
    validate_schema_or_die()


def _migrate_area_configs_into_locations():
    """One-time migration: fold the legacy area_configs table into locations.

    Each area_configs row is matched to a location by term_value == location
    (created if absent), its area fields are copied over, and it is marked
    allocatable (legacy area_configs rows were all allocation targets). The
    area_configs table is then dropped. No-op once the table is gone.
    """
    from app.db.connection import SessionLocal
    from app.db.models import Location

    inspector = inspect(engine)
    if not inspector.has_table("area_configs"):
        return

    db = SessionLocal()
    try:
        rows = db.execute(text(
            "SELECT location, region, area, price_min, price_max, "
            "bedrooms_min, bedrooms_max FROM area_configs"
        )).fetchall()

        migrated = 0
        for row in rows:
            location, region, area, price_min, price_max, bmin, bmax = row
            loc = db.query(Location).filter(Location.term_value == location).first()
            if loc is None:
                loc = Location(name=location, term_value=location, active=True)
                db.add(loc)
            loc.region = region or "South"
            loc.radius_km = area or 5
            loc.price_min = price_min
            loc.price_max = price_max
            loc.bedrooms_min = bmin
            loc.bedrooms_max = bmax
            loc.allocatable = True
            migrated += 1

        db.commit()
        db.execute(text("DROP TABLE area_configs"))
        db.commit()
        print(f"Migrated {migrated} area_config(s) into locations and dropped area_configs")
    except Exception as exc:
        db.rollback()
        print(f"area_configs → locations migration skipped: {exc}")
    finally:
        db.close()


def _seed_allocatable_locations():
    """Seed the known South London areas on a brand-new install only.

    Runs ONLY when the locations table is completely empty, so a fresh install
    gets allocator targets out of the box. On any existing install (which
    already has its own curated locations) this is a no-op — we must not inject
    the static AREA_DEFAULTS set into a populated table.
    """
    from app.db.connection import SessionLocal
    from app.db.models import Location
    from app.advisor.area_defaults import AREA_DEFAULTS

    db = SessionLocal()
    try:
        if db.query(Location).first() is not None:
            return
        seeded = 0
        for location, cfg in AREA_DEFAULTS.items():
            loc = db.query(Location).filter(Location.term_value == location).first()
            if loc is None:
                loc = Location(name=location, term_value=location, active=True)
                db.add(loc)
            loc.region = cfg.get("region", "South")
            loc.radius_km = cfg["area"]
            loc.price_min = cfg["price_min"]
            loc.price_max = cfg["price_max"]
            loc.bedrooms_min = cfg["bedrooms_min"]
            loc.bedrooms_max = cfg["bedrooms_max"]
            loc.allocatable = True
            seeded += 1
        db.commit()
        if seeded:
            print(f"Seeded {seeded} allocatable location(s) from AREA_DEFAULTS")
    except Exception as exc:
        db.rollback()
        print(f"allocatable location seed skipped: {exc}")
    finally:
        db.close()

    print("Database initialized successfully")
