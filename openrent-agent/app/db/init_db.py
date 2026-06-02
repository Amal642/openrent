from app.db.connection import engine
from app.db.models import Base
from sqlalchemy import inspect, text


REQUIRED_COLUMNS = {
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
        "worker_started_at": "DATETIME",
        "worker_last_heartbeat": "DATETIME",
        "worker_error": "TEXT",
        "worker_last_error": "TEXT",
        "worker_last_completed_at": "DATETIME",
        "current_worker_phase": "VARCHAR DEFAULT 'idle'",
        "last_login_at": "DATETIME",
        "session_status": "VARCHAR DEFAULT 'expired'",
        "session_last_checked": "DATETIME",
        "session_last_error": "TEXT",
        "session_auth_failures": "INTEGER DEFAULT 0",
        "session_captcha_triggers": "INTEGER DEFAULT 0",
        "proxy_status": "VARCHAR DEFAULT 'unknown'",
        "proxy_ip": "VARCHAR",
        "proxy_latency": "FLOAT",
        "proxy_last_checked": "DATETIME",
        "proxy_last_error": "TEXT",
        "proxy_failures": "INTEGER DEFAULT 0",
        "retry_count": "INTEGER DEFAULT 0",
        "retry_limit": "INTEGER DEFAULT 3",
        "retry_reason": "TEXT",
        "retry_next_at": "DATETIME",
        "last_exception": "TEXT",
        "permanently_failed": "BOOLEAN DEFAULT 0",
        "proxy_server": "VARCHAR",
        "proxy_username": "VARCHAR",
        "proxy_password": "VARCHAR",
        "messages_sent_reset_at": "DATETIME",
    },
    "listings": {
        "processing_owner": "VARCHAR",
        "processing_started_at": "DATETIME",
    },
    "conversations": {
        "ai_error_reason": "TEXT",
        "conversation_stage": "VARCHAR DEFAULT 'NEW_LEAD'",
        "viewing_datetime": "DATETIME",
        "last_stage_change": "DATETIME",
        "phone_requested_at": "DATETIME",
        "phone_found_at": "DATETIME",
        "phone_number_shared_at": "DATETIME",
        "landlord_asked_phone_at": "DATETIME",
        "landlord_attitude": "VARCHAR DEFAULT 'responsive'",
        "conversation_style": "VARCHAR",
        "viewing_confirmed": "BOOLEAN DEFAULT 0",
        "viewing_cancelled": "BOOLEAN DEFAULT 0",
        "cancel_required": "BOOLEAN DEFAULT 1",
        "cancellation_sent_at": "DATETIME",
        "processing_owner": "VARCHAR",
        "processing_started_at": "DATETIME",
    },
}


def apply_schema_updates():
    inspector = inspect(engine)

    with engine.begin() as connection:
        for table_name, columns in REQUIRED_COLUMNS.items():
            existing_columns = {
                column["name"]
                for column in inspector.get_columns(table_name)
            }

            for column_name, column_type in columns.items():
                if column_name in existing_columns:
                    continue

                connection.execute(
                    text(
                        f"ALTER TABLE {table_name} "
                        f"ADD COLUMN {column_name} {column_type}"
                    )
                )


def init_db():
    Base.metadata.create_all(bind=engine)
    apply_schema_updates()

    print("Database initialized successfully")
