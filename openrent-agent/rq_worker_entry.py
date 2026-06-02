from rq import Worker
from app.queue.redis_conn import redis_conn

worker = Worker(
    ["workers"],
    connection=redis_conn
)

worker.work()
