"""A local server standing in for a LangSmith that hangs, refuses or limits request rates."""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

KEY = "planted-not-a-key-L1B"
MODES = ("hang", "error", "rate-limit")


def start_server(mode: str) -> ThreadingHTTPServer:
    """Serve on a free local port; the caller shuts it down."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: object) -> None:
            return

        def _answer(self) -> None:
            length = int(self.headers.get("content-length") or 0)
            if length:
                self.rfile.read(length)
            if mode == "hang":
                time.sleep(30)
                return
            status = 429 if mode == "rate-limit" else 500
            body = b'{"detail":"planted failure"}'
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        do_GET = _answer  # noqa: N815 - the names the server calls
        do_POST = _answer  # noqa: N815

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def environment(server: ThreadingHTTPServer) -> dict[str, str]:
    """The environment that points tracing at the server."""
    return {
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": KEY,
        "LANGSMITH_ENDPOINT": f"http://127.0.0.1:{server.server_address[1]}",
    }
