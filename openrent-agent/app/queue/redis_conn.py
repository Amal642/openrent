from redis import Redis
import os
from dotenv import load_dotenv

load_dotenv()

redis_conn = Redis.from_url(
    os.getenv("REDIS_URL"),
)
