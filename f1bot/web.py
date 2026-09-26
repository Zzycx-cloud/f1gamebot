"""Tiny HTTP health-check server for hosts like Render.com.

Cloud platforms that run "Web Services" require the process to listen on a
TCP port (``PORT`` env var) or they kill it as unhealthy. The bot itself is a
long-polling Telegram client, so we expose a minimal ``/`` and ``/health``
endpoint in a background thread and keep polling in the main asyncio loop.
"""

from __future__ import annotations

import logging
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger("f1bot.web")

HTML = (
    "<!doctype html><html><head><meta charset='utf-8'><title>F1 Game Bot</title>"
    "<style>body{font-family:system-ui,sans-serif;background:#0d0d1a;color:#fff;"
    "display:grid;place-items:center;height:100vh;margin:0}div{text-align:center}"
    "h1{font-size:3rem;margin:0}p{color:#aaa}</style></head>"
    "<body><div><h1>🏎️ F1 GAME</h1><p>Telegram bot is running.</p></div></body></html>"
)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path.startswith("/health"):
            body = b'{"status":"ok"}'
            ctype = "application/json"
        else:
            body = HTML.encode("utf-8")
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        log.debug("health: " + format, *args)


def port() -> int:
    """Render injects PORT; fall back to the common 10000/8080 defaults."""
    raw = os.getenv("PORT", "").strip()
    try:
        return int(raw) if raw else 10000
    except ValueError:
        return 10000


def start_health_server() -> int | None:
    """Bind 0.0.0.0:$PORT in a daemon thread. Returns the port or None."""
    try:
        server = ThreadingHTTPServer(("0.0.0.0", port()), HealthHandler)
        server.daemon_threads = True
        import threading

        thread = threading.Thread(target=server.serve_forever, name="health", daemon=True)
        thread.start()
        log.info("Health server listening on 0.0.0.0:%s", server.server_address[1])
        return int(server.server_address[1])
    except OSError as exc:
        log.warning("Health server not started: %s", exc)
        return None
