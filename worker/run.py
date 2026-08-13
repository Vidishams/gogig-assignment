import os
import logging

from redis import Redis
from rq import Worker, Queue

logging.basicConfig(level=logging.INFO)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

if __name__ == "__main__":
    conn = Redis.from_url(REDIS_URL)

    queue = Queue("image_analysis", connection=conn)

    worker = Worker(
        [queue],
        connection=conn
    )

    worker.work(with_scheduler=True)