"""Print and export a sanitized excerpt of each failed survey check's log.

`ci_diagnostics.py` exports fixed categories only; a failed CI shard also
needs the failing test names, the assertion message and the last service
lines to be diagnosable. This script takes, per failed check of this run, the
lines that look like failures plus the log tail, and passes them through the
same sanitizer as every other CI artifact (tools/ci/sanitize_artifacts.py).

The repository is public, so redaction runs on the full text before any line
is cut, in this order:
1. exact values of known secrets (`.env.local`, every `*.env` of the run,
   including the Twenty key provisioned at runtime);
2. generic credential shapes that are created at runtime and never appear in
   an env file: Authorization/Bearer values, Cookie/Set-Cookie headers,
   token/code/key/signature/X-Amz-* query parameters, `password=`-style
   assignments, JWTs and long opaque base64/hex strings.
Afterwards the PII check of the sanitizer withholds the whole excerpt on a
personal e-mail, phone or canary signature, and a leftover credential keyword
with a value withholds it as well (on doubt, withhold). Raw logs stay private.

Usage: ci_failure_excerpt.py ROOT DESTINATION.json
(The public upload allowlist, tools/pilot/boundary.py, admits only JSON results.)
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from tools.ci import sanitize_artifacts  # noqa: E402

ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
FAILURE_LINE = re.compile(
    r"(✘|✗|×|\bFAIL|\bfailed\b|Error\b|error:|AssertionError|Traceback|"
    r"expect\(|Expected|Received|Timeout|timed out|unhealthy|exit code|exited with)",
)
# Compose progress lines carry no diagnosis and would fill the whole tail.
COMPOSE_PROGRESS = re.compile(
    r"^\s*(?:Container|Volume|Network|Image)\s+\S+\s+"
    r"(?:Creating|Created|Starting|Started|Waiting|Healthy|Stopping|Stopped|"
    r"Removing|Removed|Recreate|Recreated|Running|Exited|Pulling|Pulled)\s*$"
    r"|^\s*\S+\s+(?:Built|Pulled|Pulling)\s*$"
)
REDACTED = "[REDACTED]"
GENERIC_SECRETS = (
    # Authorization headers and bearer tokens.
    re.compile(r"(?i)(authorization\s*[:=]\s*)[^\r\n]+"),
    re.compile(r"(?i)(\bbearer\s+)[A-Za-z0-9._~+/=-]+"),
    # Cookie and Set-Cookie headers, including Playwright's object form.
    re.compile(r"(?i)((?:set-)?cookie\s*[:=]\s*)[^\r\n]+"),
    # Credentials in URLs and query strings.
    re.compile(
        r"(?i)([?&;](?:token|access_token|code|key|api_key|signature|sig|"
        r"x-amz-[a-z-]+|session|secret|password)=)[^&\s\"'<>]+"
    ),
    re.compile(r"(?i)(://[^/\s:@]+:)[^@\s/]+(@)"),
    # Assignments and JSON fields with a credential name.
    re.compile(
        r"(?i)((?:\"|\b)[a-z_-]*(?:password|passwd|secret|token|api[_-]?key|"
        r"session|cookie|credential|signature)[a-z_-]*\"?\s*[:=]\s*\"?)"
        r"[^\s\",;&]+"
    ),
    # JSON Web Tokens.
    re.compile(r"()\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*"),
)
# Long opaque strings: hex digests/keys and mixed-case base64(url) values.
OPAQUE = re.compile(r"(?<![A-Za-z0-9_+/=-])[A-Za-z0-9_+/=-]{32,}(?![A-Za-z0-9_+/=-])")
HEX = re.compile(r"[0-9a-fA-F]{32,}")
# After redaction a credential keyword must not be followed by a value.
LEFTOVER = re.compile(
    r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|bearer|cookie)s?\b"
    r"[\"']?\s*(?:[:=]|->|is)?\s*[\"']?(?!\[REDACTED)"
    r"(?=[^\s\"']*\d)[A-Za-z0-9+/_.~-]{8,}"
)
MAX_FAILURE_LINES = 80
TAIL_LINES = 150
MAX_LINE = 400
READ_BYTES = 4 * 1024 * 1024
# Logs of checks that run their own foundation harness.
FOUNDATION_LOGS = {
    "foundation-diagnostics": "infrastructure",
    "foundation-failure": "infrastructure-failure",
}


def failed_checks(root: Path) -> list[tuple[int, str]]:
    failed: set[tuple[int, str]] = set()
    for report in sorted((root / ".artifacts/surveys-gate/results").glob("*.json")):
        try:
            data = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for check in data.get("checks", []) if isinstance(data, dict) else []:
            if (
                isinstance(check, dict)
                and check.get("exitCode")
                and isinstance(check.get("pass"), int)
                and re.fullmatch(r"[a-z][a-z0-9-]*", str(check.get("id", "")))
            ):
                failed.add((check["pass"], check["id"]))
    return sorted(failed)


def read_tail(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        return ""
    with path.open("rb") as stream:
        size = path.stat().st_size
        stream.seek(max(0, size - READ_BYTES))
        return stream.read().decode("utf-8", errors="replace")


class Withheld(RuntimeError):
    """The excerpt may still contain a credential."""


def opaque(match: re.Match[str]) -> str:
    value = match.group(0)
    if HEX.fullmatch(value):
        return REDACTED
    has_digit = any(c.isdigit() for c in value)
    has_upper = any(c.isupper() for c in value)
    has_lower = any(c.islower() for c in value)
    # Compose names, paths and slugs are lower-case words; secrets are mixed.
    if has_upper and has_lower and has_digit:
        return REDACTED
    return value


def replace(match: re.Match[str]) -> str:
    prefix = match.group(1)
    value = match.group(0)[len(prefix) :]
    if value.startswith("[REDACTED"):
        return match.group(0)
    suffix = match.group(2) if (match.re.groups or 0) >= 2 else ""
    return prefix + REDACTED + (suffix or "")


def redact(text: str, known: dict[str, str]) -> str:
    """Redact on the full text, before any truncation."""
    for key, value in sorted(known.items(), key=lambda item: -len(item[1])):
        text = text.replace(value, f"[REDACTED:{key}]")
    text = ANSI.sub("", text)
    for pattern in GENERIC_SECRETS:
        text = pattern.sub(replace, text)
    text = OPAQUE.sub(opaque, text)
    if LEFTOVER.search(text):
        raise Withheld("credential keyword with a value left after redaction")
    return text


def excerpt(text: str) -> str:
    lines = [
        clean
        for line in text.splitlines()
        if not COMPOSE_PROGRESS.match(clean := ANSI.sub("", line)[:MAX_LINE])
    ]
    tail_start = max(0, len(lines) - TAIL_LINES)
    failures = [
        line
        for line in lines[:tail_start]
        if FAILURE_LINE.search(line)
    ][-MAX_FAILURE_LINES:]
    parts = []
    if failures:
        parts += ["--- failure lines before the tail ---", *failures]
    parts += [
        f"--- last {len(lines) - tail_start} lines (Compose progress omitted) ---",
        *lines[tail_start:],
    ]
    return "\n".join(parts) + "\n"


def runtime_keys() -> dict[str, str]:
    """Keys provisioned at runtime: the prepared fixture's Twenty key and env."""
    found = {}
    fixture = os.environ.get("LEONAID_CI_FIXTURE")
    if fixture:
        directory = Path(fixture)
        try:
            manifest = json.loads((directory / "manifest.json").read_text())
            key = manifest.get("integrationKey", "")
            if isinstance(key, str) and len(key) >= 8:
                found["TWENTY_INTEGRATION_API_KEY"] = key
        except (OSError, json.JSONDecodeError):
            pass
        found.update(sanitize_artifacts.secrets_from(directory / "integration.env"))
    value = os.environ.get("TWENTY_INTEGRATION_API_KEY", "")
    if len(value) >= 8:
        found["TWENTY_INTEGRATION_API_KEY_ENV"] = value
    return found


def secrets(root: Path) -> dict[str, str]:
    found = sanitize_artifacts.secrets_from(root / ".env.local")
    found.update(runtime_keys())
    for directory in (
        root / ".artifacts/surveys-gate",
        root / ".artifacts/foundation-acceptance",
    ):
        if directory.is_dir():
            for env_file in directory.rglob("*.env"):
                if not env_file.is_symlink():
                    found.update(sanitize_artifacts.secrets_from(env_file))
    return found


def logs_for(root: Path, iteration: int, check: str) -> list[tuple[str, Path]]:
    found = [
        (f"{iteration}-{check}", path)
        for path in sorted(
            (root / ".artifacts/surveys-gate").glob(f"private-*/{iteration}-{check}.log")
        )
    ]
    if check in FOUNDATION_LOGS:
        name = FOUNDATION_LOGS[check]
        found.append(
            (f"{check}-harness", root / f".artifacts/foundation-acceptance/{name}.log")
        )
    return found


def export(root: Path, destination: Path) -> list[tuple[str, str]]:
    """Write sanitized excerpts as JSON; return (label, public text) for printing."""
    known = secrets(root)
    printed = []
    for iteration, check in failed_checks(root):
        for label, path in logs_for(root, iteration, check):
            raw = read_tail(path)
            if not raw:
                continue
            try:
                result = sanitize_artifacts.sanitize_text(
                    excerpt(redact(raw, known)).encode("utf-8"),
                    label=f"{label}.log",
                    suffix=".log",
                    secrets=known,
                )
                public = result.payload.decode("utf-8")
            except (sanitize_artifacts.SanitizationFailure, Withheld) as error:
                # The reason names only the rule and the file, never the data.
                public = f"Excerpt withheld by the artifact sanitizer: {error}\n"
            printed.append((label, public))
    payload = json.dumps(
        {
            "schemaVersion": 1,
            "scope": "sanitized excerpts of failed checks: failure lines and log tail",
            "excerpts": [{"source": label, "text": text} for label, text in printed],
        },
        indent=2,
    ).encode("utf-8")
    try:
        payload = sanitize_artifacts.sanitize_text(
            payload, label=destination.name, suffix=".json", secrets=known
        ).payload
    except sanitize_artifacts.SanitizationFailure as error:
        printed = [("all", f"Excerpts withheld by the artifact sanitizer: {error}\n")]
        payload = json.dumps({"schemaVersion": 1, "excerpts": []}).encode("utf-8")
    if printed:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(payload)
        destination.chmod(0o644)
    return printed


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 64
    printed = export(Path(argv[1]).resolve(), Path(argv[2]))
    for label, public in printed:
        print(f"::group::Sanitized failure excerpt: {label}")
        print(public, end="")
        print("::endgroup::")
    print(f"survey-failure-excerpt: {len(printed)} sanitized excerpt(s) written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
