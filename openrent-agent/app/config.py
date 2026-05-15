import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    EMAIL = os.getenv("EMAIL")
    PASSWORD = os.getenv("PASSWORD")

    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

    DATABASE_URL = os.getenv("DATABASE_URL")

    HEADLESS = os.getenv("HEADLESS", "false").lower() == "true"
    SLOW_MO = int(os.getenv("SLOW_MO", 500))

    SESSION_FILE = os.getenv("SESSION_FILE", "session.json")

    PROXY_SERVER = os.getenv("PROXY_SERVER")
    PROXY_USERNAME = os.getenv("PROXY_USERNAME")
    PROXY_PASSWORD = os.getenv("PROXY_PASSWORD")

    AI_AUTOSEND: bool = False
    OPENAI_REPLY_MODEL = os.getenv("OPENAI_REPLY_MODEL", "gpt-4.1-mini")
    OPENAI_REPLY_TEMPERATURE = float(
        os.getenv("OPENAI_REPLY_TEMPERATURE", "0.7")
    )
    SIMULATION_DEFAULT_TEMPERATURE = float(
        os.getenv("SIMULATION_DEFAULT_TEMPERATURE", "0")
    )
    SIMULATION_MAX_FOLLOWUPS = int(
        os.getenv("SIMULATION_MAX_FOLLOWUPS", "1")
    )

settings = Settings()
