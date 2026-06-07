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

settings = Settings()
