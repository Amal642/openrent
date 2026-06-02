from rq import Queue
from app.queue.redis_conn import redis_conn

worker_queue = Queue(
    "workers",
    connection=redis_conn
)
