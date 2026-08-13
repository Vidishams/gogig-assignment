import os
from redis import Redis
from rq import Queue

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

redis_conn = Redis.from_url(REDIS_URL)

image_queue = Queue(
    "image_analysis",
    connection=redis_conn,
    default_timeout=120
)