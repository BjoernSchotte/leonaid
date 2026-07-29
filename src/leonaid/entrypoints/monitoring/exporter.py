"""Expose host-adjacent pilot signals without payloads or Docker privileges."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
import socket
import ssl
from typing import Any

REQUIRED_BACKUP_FILES = {
    "core.dump",
    "rustfs-data.tar",
    "twenty-storage.tar",
    "twenty.dump",
}
SHA256 = re.compile(r"^[0-9a-f]{64}$")
BACKUP_MAX_AGE_SECONDS = 93_600
DISK_MIN_FREE_RATIO = 0.10
TLS_MIN_REMAINING_SECONDS = 1_209_600


def _backup_metrics(path: Path, *, expected_project: str) -> tuple[int, float]:
    try:
        document: Any = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            return 0, 0.0
        if (
            document.get("schemaVersion") != 1
            or document.get("sourceProject") != expected_project
            or not isinstance(document.get("files"), dict)
            or set(document["files"]) != REQUIRED_BACKUP_FILES
        ):
            return 0, 0.0
        for metadata in document["files"].values():
            if (
                not isinstance(metadata, dict)
                or not isinstance(metadata.get("size"), int)
                or metadata["size"] < 0
                or not isinstance(metadata.get("sha256"), str)
                or SHA256.fullmatch(metadata["sha256"]) is None
            ):
                return 0, 0.0
        created_at = datetime.fromisoformat(str(document["createdAt"]))
        if created_at.tzinfo is None:
            return 0, 0.0
        age = (datetime.now(timezone.utc) - created_at).total_seconds()
        if age < -300:
            return 0, 0.0
        return 1, max(0.0, age)
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return 0, 0.0


def _disk_metrics(path: Path) -> tuple[int, int, float]:
    try:
        usage = shutil.disk_usage(path)
    except OSError:
        return 0, 0, 0.0
    ratio = usage.free / usage.total if usage.total else 0.0
    return 1, usage.free, ratio


def _certificate_metrics(
    host: str,
    *,
    port: int,
    ca_file: str | None,
) -> tuple[int, float]:
    try:
        context = ssl.create_default_context(cafile=ca_file)
        with socket.create_connection((host, port), timeout=3) as connection:
            with context.wrap_socket(connection, server_hostname=host) as tls:
                certificate = tls.getpeercert()
        if certificate is None:
            return 0, 0.0
        not_after = certificate.get("notAfter")
        if not isinstance(not_after, str):
            return 0, 0.0
        remaining = (
            ssl.cert_time_to_seconds(not_after) - datetime.now(timezone.utc).timestamp()
        )
        return 1, remaining
    except (OSError, ssl.SSLError, ValueError):
        return 0, 0.0


def collect_status() -> dict[str, Any]:
    backup_valid, backup_age = _backup_metrics(
        Path(os.environ["PILOT_BACKUP_MANIFEST_PATH"]),
        expected_project=os.environ["PILOT_BACKUP_SOURCE_PROJECT"],
    )
    disk_valid, disk_free, disk_ratio = _disk_metrics(
        Path(os.environ["PILOT_MONITORED_DISK_PATH"])
    )
    certificate_valid, certificate_remaining = _certificate_metrics(
        os.environ["PILOT_TLS_HOST"],
        port=int(os.environ.get("PILOT_TLS_PORT", "443")),
        ca_file=os.environ.get("PILOT_TLS_CA_FILE") or None,
    )
    return {
        "checkedAt": datetime.now(timezone.utc).isoformat(),
        "backup": {
            "valid": bool(backup_valid),
            "ageSeconds": backup_age,
            "status": (
                "ready"
                if backup_valid and backup_age <= BACKUP_MAX_AGE_SECONDS
                else "critical"
            ),
        },
        "disk": {
            "valid": bool(disk_valid),
            "freeBytes": disk_free,
            "freeRatio": disk_ratio,
            "status": (
                "ready"
                if disk_valid and disk_ratio >= DISK_MIN_FREE_RATIO
                else "critical"
            ),
        },
        "tls": {
            "valid": bool(certificate_valid),
            "remainingSeconds": certificate_remaining,
            "status": (
                "ready"
                if certificate_valid
                and certificate_remaining >= TLS_MIN_REMAINING_SECONDS
                else "critical"
            ),
        },
    }


def render_metrics() -> str:
    status = collect_status()
    backup = status["backup"]
    disk = status["disk"]
    tls = status["tls"]
    return "\n".join(
        (
            "# HELP leonaid_backup_manifest_valid Whether the latest backup manifest is complete and scoped.",
            "# TYPE leonaid_backup_manifest_valid gauge",
            f"leonaid_backup_manifest_valid {int(backup['valid'])}",
            "# HELP leonaid_backup_age_seconds Age of the latest complete cross-system backup.",
            "# TYPE leonaid_backup_age_seconds gauge",
            f"leonaid_backup_age_seconds {backup['ageSeconds']:.3f}",
            "# HELP leonaid_monitored_disk_valid Whether the configured data filesystem can be measured.",
            "# TYPE leonaid_monitored_disk_valid gauge",
            f"leonaid_monitored_disk_valid {int(disk['valid'])}",
            "# HELP leonaid_monitored_disk_free_bytes Free bytes on the pilot data filesystem.",
            "# TYPE leonaid_monitored_disk_free_bytes gauge",
            f"leonaid_monitored_disk_free_bytes {disk['freeBytes']}",
            "# HELP leonaid_monitored_disk_free_ratio Free fraction of the pilot data filesystem.",
            "# TYPE leonaid_monitored_disk_free_ratio gauge",
            f"leonaid_monitored_disk_free_ratio {disk['freeRatio']:.8f}",
            "# HELP leonaid_tls_certificate_valid Whether the public certificate chain and hostname validate.",
            "# TYPE leonaid_tls_certificate_valid gauge",
            f"leonaid_tls_certificate_valid {int(tls['valid'])}",
            "# HELP leonaid_tls_certificate_expiry_seconds Seconds until the public certificate expires.",
            "# TYPE leonaid_tls_certificate_expiry_seconds gauge",
            f"leonaid_tls_certificate_expiry_seconds {tls['remainingSeconds']:.3f}",
            "",
        )
    )


class MetricsHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        if self.path == "/health/live":
            self._respond(
                200,
                b'{"service":"leonaid-pilot-exporter","status":"live"}',
                "application/json",
            )
            return
        if self.path == "/metrics":
            self._respond(
                200,
                render_metrics().encode(),
                "text/plain; version=0.0.4; charset=utf-8",
            )
            return
        if self.path == "/status":
            self._respond(
                200,
                json.dumps(
                    collect_status(),
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ).encode(),
                "application/json",
            )
            return
        self._respond(404, b'{"status":"not-found"}', "application/json")

    def _respond(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8020), MetricsHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
