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
        "worker_status": "VARCHAR DEFAULT 'idle'",
        "worker_last_heartbeat": "DATETIME",
        "worker_last_error": "TEXT",
        "current_worker_phase": "VARCHAR DEFAULT 'idle'",
        "last_login_at": "DATETIME",
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
