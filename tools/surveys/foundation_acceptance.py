"""Prove passing/failing real browser runs, safe diagnostics and owned teardown."""

import json
from pathlib import Path
import subprocess
import sys

root = Path(sys.argv[1]).resolve()
reports = root / ".artifacts/surveys-infrastructure/foundation"
output = root / ".artifacts/foundation-acceptance"
output.mkdir(parents=True, exist_ok=True)
evidence = []
modes = (("infrastructure", 0), ("infrastructure-failure", 1))
if len(sys.argv) > 2:
    assert sys.argv[2] in {mode for mode, _ in modes}
    modes = tuple(pair for pair in modes if pair[0] == sys.argv[2])
for mode, expected in modes:
    before = set(reports.glob("*.json"))
    log = output / f"{mode}.log"
    print(f"Starting isolated {mode} browser run", flush=True)
    with log.open("w") as stream:
        result = subprocess.run(
            ["sh", str(root / "tools/surveys/infrastructure.sh"), str(root), mode],
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    assert result.returncode == expected, (mode, result.returncode)
    created = set(reports.glob("*.json")) - before
    assert len(created) == 1, "Expected exactly one new diagnostic"
    report = json.loads(created.pop().read_text())
    assert report["commandExitCode"] == expected
    assert report["status"] == ("passed" if expected == 0 else "failed")
    assert report["credentialScanPassed"] is True
    assert report["globalErrors"] == 0
    assert report["completedPhases"] == [
        "member-host",
        "public-host",
        "public-survey-shell",
    ]
    assert len(report["cases"]) == 1
    if expected:
        error = report["cases"][0]["errors"][0]
        assert error["category"] == "assertion"
        assert error["location"]["file"] == "tests/e2e/surveys-infrastructure.spec.mjs"
        assert error["location"]["line"] > 0
    else:
        assert report["cases"][0]["errors"] == []
    assert "SURVEY_FOUNDATION_SECRET_CANARY" not in log.read_text()
    for command in (
        ["docker", "ps", "-aq"],
        ["docker", "volume", "ls", "-q"],
        ["docker", "network", "ls", "-q"],
    ):
        remaining = subprocess.check_output(
            [
                *command,
                "--filter",
                f"label=com.docker.compose.project={report['project']}",
            ],
            text=True,
        )
        assert not remaining.strip(), "Owned project resources survived cleanup"
    report["ownedContainersVolumesNetworksRemoved"] = True
    report["rawErrorCanaryAbsentFromCommandLog"] = True
    evidence.append(report)
    print(
        f"PASS: {mode}, expected exit {expected}, retained safe diagnostic and verified teardown",
        flush=True,
    )
if len(evidence) == 2:
    assert evidence[0]["project"] != evidence[1]["project"]
(output / "proof.json").write_text(json.dumps({"runs": evidence}, indent=2) + "\n")
