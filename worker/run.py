import os
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from redis import Redis
from rq import Worker, Queue

logging.basicConfig(level=logging.INFO)

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"worker running"}')

    def log_message(self, *args):
        pass


def _maybe_start_health_server():
    port = os.getenv("PORT")
    if not port:
        return
    server = HTTPServer(("0.0.0.0", int(port)), _HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logging.getLogger("gogig-worker").info(f"Health-check server listening on :{port}")


if __name__ == "__main__":
    _maybe_start_health_server()
    conn = Redis.from_url(REDIS_URL)
    queue = Queue("image_analysis", connection=conn)
    worker = Worker([queue], connection=conn)
    worker.work(with_scheduler=True)