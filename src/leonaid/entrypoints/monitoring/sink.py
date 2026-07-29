"""Private test-only webhook sink for proving real Alertmanager delivery."""

from __future__ import annotations

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading
from typing import Any

MAX_BODY_BYTES = 1_048_576
EVENTS_PATH = Path(os.environ.get("ALERT_SINK_EVENTS_PATH", "/events/events.jsonl"))
WRITE_LOCK = threading.Lock()


class AlertSinkHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path == "/health/live":
            self._respond(200, b'{"status":"live"}')
            return
        self._respond(404, b'{"status":"not-found"}')

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path != "/alerts":
            self._respond(404, b'{"status":"not-found"}')
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._respond(400, b'{"status":"invalid"}')
            return
        if length < 1 or length > MAX_BODY_BYTES:
            self._respond(413, b'{"status":"rejected"}')
            return
        try:
            payload: Any = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._respond(400, b'{"status":"invalid"}')
            return
        if not isinstance(payload, dict):
            self._respond(400, b'{"status":"invalid"}')
            return
        event = {
            "receivedAt": datetime.now(timezone.utc).isoformat(),
            "payload": payload,
        }
        EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with WRITE_LOCK, EVENTS_PATH.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    event,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n"
            )
        self._respond(202, b'{"status":"accepted"}')

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    ThreadingHTTPServer(("0.0.0.0", 8080), AlertSinkHandler).serve_forever()


if __name__ == "__main__":
    main()
