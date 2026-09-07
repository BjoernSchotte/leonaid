"""Retain only the bounded foundation report, after checking actual credentials."""

import json
from pathlib import Path
import sys

proof, artifact = map(Path, sys.argv[1:3])
project, exit_code = sys.argv[3], int(sys.argv[4])
source = proof / "foundation-diagnostics.json"
if not source.is_file():
    raise SystemExit("Foundation diagnostic missing; browser acceptance is unproven")
data = source.read_bytes()
assert b"SURVEY_FOUNDATION_SECRET_CANARY" not in data, "Unsafe diagnostic marker"
for line in (proof / "session.env").read_text().splitlines():
    if "=" in line:
        value = line.split("=", 1)[1]
        if value:
            assert value.encode() not in data, (
                "Credential or fixture identifier in diagnostic"
            )
report = json.loads(data)
assert set(report) == {
    "schemaVersion",
    "status",
    "completedPhases",
    "globalErrors",
    "cases",
}
report.update(
    {"project": project, "commandExitCode": exit_code, "credentialScanPassed": True}
)
artifact.mkdir(parents=True, exist_ok=True)
(artifact / f"{project}.json").write_text(json.dumps(report, indent=2) + "\n")
print(
    "Foundation diagnostic retained without messages, traces, credentials or attachments"
)
