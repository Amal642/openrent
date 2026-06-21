import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    EMAIL = os.getenv("EMAIL")
    PASSWORD = os.getenv("PASSWORD")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_REPLY_MODEL = os.getenv("OPENAI_REPLY_MODEL", "gpt-4.1-mini")

    DATABASE_URL = os.getenv("DATABASE_URL")

    HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"
    SLOW_MO = int(os.getenv("SLOW_MO", 500))
    PLAYWRIGHT_BLOCK_IMAGE_MEDIA = (
        os.getenv("PLAYWRIGHT_BLOCK_IMAGE_MEDIA", "true").lower()
        not in {"0", "false", "no", "off"}
    )

    SESSION_FILE = os.getenv("SESSION_FILE", "session.json")

    PROXY_SERVER = os.getenv("PROXY_SERVER")
    PROXY_USERNAME = os.getenv("PROXY_USERNAME")
    PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")

    AI_AUTOSEND: bool = os.getenv("AI_AUTOSEND", "true").lower() == "true"
    WORKER_TICK_SECONDS = int(os.getenv("WORKER_TICK_SECONDS", "300"))
    MAX_PARALLEL_WORKERS = int(os.getenv("MAX_PARALLEL_WORKERS", "2"))
    DISCOVERY_LIMIT_PER_RUN = int(os.getenv("DISCOVERY_LIMIT_PER_RUN", "25"))
    DISCOVERY_LIMIT_PER_DAY = int(os.getenv("DISCOVERY_LIMIT_PER_DAY", "100"))
    DISCOVERY_COOLDOWN_HOURS = int(os.getenv("DISCOVERY_COOLDOWN_HOURS", "4"))
    TARGET_INVENTORY = int(os.getenv("TARGET_INVENTORY", "50"))
    HARD_CAP_INVENTORY = int(os.getenv("HARD_CAP_INVENTORY", "100"))
    SIMULATION_DEFAULT_TEMPERATURE = float(
        os.getenv("SIMULATION_DEFAULT_TEMPERATURE", "0.0")
    )
    SIMULATION_MAX_FOLLOWUPS = int(
        os.getenv("SIMULATION_MAX_FOLLOWUPS", "1")
    )

    GOOGLE_SHEETS_ENABLED = (
        os.getenv("GOOGLE_SHEETS_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"}
    )
    GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
    GOOGLE_SHEET_PERSON = os.getenv("GOOGLE_SHEET_PERSON", "Becky")
    GOOGLE_SHEET_TAB = os.getenv("GOOGLE_SHEET_TAB", "Becky")
    GOOGLE_SHEET_LOCATION = os.getenv("GOOGLE_SHEET_LOCATION", "London")
    GOOGLE_SHEET_DIRECTION = os.getenv("GOOGLE_SHEET_DIRECTION", "")
    GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    GOOGLE_SHEETS_DISPATCH_SECONDS = int(
        os.getenv("GOOGLE_SHEETS_DISPATCH_SECONDS", "60")
    )
    GOOGLE_SHEETS_MAX_ATTEMPTS = int(
        os.getenv("GOOGLE_SHEETS_MAX_ATTEMPTS", "8")
    )

settings = Settings()
