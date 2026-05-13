from app.db.connection import engine
from app.db.models import Base
from sqlalchemy import inspect, text


REQUIRED_COLUMNS = {
    "conversations": {
        "ai_error_reason": "TEXT",
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
