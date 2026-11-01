#!/usr/bin/env python3
"""Strict contract test for the systemd backup units in infra/pilot/systemd.

`systemd-analyze verify` needs a systemd host, which the pinned check images do
not have. This parser therefore enforces the subset of the unit syntax the
units use and cross-checks them against ./leonaid pilot-backup, the example
EnvironmentFile and the 26-hour backup age that the doctor and the
LeonAidBackupStale alert require.
"""

from __future__ import annotations

import re
import shlex
import shutil
import sys
import tempfile
from datetime import timedelta
from pathlib import Path

ALLOWED = {
    "service": {
        "Unit": {"Description", "Documentation", "Requires", "After", "Wants"},
        "Service": {
            "Type",
            "User",
            "Group",
            "EnvironmentFile",
            "UMask",
            "NoNewPrivileges",
            "Nice",
            "IOSchedulingClass",
            "IOSchedulingPriority",
            "TimeoutStartSec",
            "ExecStart",
        },
    },
    "timer": {
        "Unit": {"Description"},
        "Timer": {
            "OnCalendar",
            "RandomizedDelaySec",
            "AccuracySec",
            "Persistent",
            "Unit",
        },
        "Install": {"WantedBy"},
    },
}
# The doctor and LeonAidBackupStale both allow 26 hours between backups.
MAXIMUM_BACKUP_GAP = timedelta(hours=26)
TIME_SPAN = re.compile(r"^(\d+)(s|min|h)$")
TIME_UNITS = {"s": "seconds", "min": "minutes", "h": "hours"}


class UnitError(AssertionError):
    """A unit file violates the backup schedule contract."""


def parse_unit(path: Path, kind: str) -> dict[str, dict[str, str]]:
    sections: dict[str, dict[str, str]] = {}
    current: str | None = None
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.endswith("\\"):
            raise UnitError(f"{path.name}:{number}: continuation lines are not used")
        section = re.fullmatch(r"\[([A-Za-z]+)\]", line)
        if section:
            current = section.group(1)
            if current not in ALLOWED[kind]:
                raise UnitError(f"{path.name}:{number}: unexpected [{current}]")
            if current in sections:
                raise UnitError(f"{path.name}:{number}: duplicate [{current}]")
            sections[current] = {}
            continue
        if current is None:
            raise UnitError(f"{path.name}:{number}: setting outside a section")
        match = re.fullmatch(r"([A-Za-z]+)=(.*)", line)
        if not match:
            raise UnitError(f"{path.name}:{number}: expected Key=Value")
        key, value = match.groups()
        if key not in ALLOWED[kind][current]:
            raise UnitError(
                f"{path.name}:{number}: {key} is not allowed in [{current}]"
            )
        if key in sections[current]:
            raise UnitError(f"{path.name}:{number}: duplicate {key}")
        if not value:
            raise UnitError(f"{path.name}:{number}: {key} is empty")
        sections[current][key] = value
    return sections


def time_span(value: str) -> timedelta:
    match = TIME_SPAN.fullmatch(value)
    if not match:
        raise UnitError(f"unsupported time span {value!r}")
    return timedelta(**{TIME_UNITS[match.group(2)]: int(match.group(1))})


def read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key in values:
            raise UnitError(f"{path.name}: invalid or duplicate line {line!r}")
        values[key] = value
    return values


def backup_options(cli: Path) -> tuple[set[str], set[str]]:
    """Accepted and required options of the real pilot_backup function."""
    text = cli.read_text(encoding="utf-8")
    body = text.split("\npilot_backup() {\n", 1)[1].split("\n}\n", 1)[0]
    accepted = set(re.findall(r"^      (--[a-z-]+)\)$", body, re.MULTILINE))
    required = set(re.findall(r'echo "pilot-backup: ERROR: (--[a-z-]+) fehlt"', body))
    if not accepted or not required <= accepted:
        raise UnitError("cannot read the pilot-backup options from ./leonaid")
    return accepted, required


def check(root: Path) -> None:
    directory = root / "infra/pilot/systemd"
    service = parse_unit(directory / "leonaid-backup.service", "service")
    timer = parse_unit(directory / "leonaid-backup.timer", "timer")
    environment = read_env(directory / "backup.env.example")

    unit = service.get("Unit", {})
    if "docker.service" not in unit.get("Requires", "").split():
        raise UnitError("the backup must require docker.service")
    if "docker.service" not in unit.get("After", "").split():
        raise UnitError("the backup must start after docker.service")

    settings = service.get("Service", {})
    expected = {
        "Type": "oneshot",
        "User": "leonaid",
        "Group": "leonaid",
        "EnvironmentFile": "/etc/leonaid/backup.env",
        "UMask": "0077",
        "NoNewPrivileges": "yes",
    }
    for key, value in expected.items():
        if settings.get(key) != value:
            raise UnitError(f"leonaid-backup.service needs {key}={value}")
    # PrivateTmp/ProtectSystem would hide the temp files that ./leonaid binds
    # into containers from the Docker daemon; the allowlist keeps them out.
    if time_span(settings["TimeoutStartSec"]) < timedelta(hours=1):
        raise UnitError("TimeoutStartSec is too short for a full backup")

    command = shlex.split(settings["ExecStart"])
    if command[:3] != ["/bin/sh", "-eu", "-c"] or len(command) != 4:
        raise UnitError("ExecStart must run one /bin/sh -eu -c script")
    script = command[3]
    if "$" in script.replace("$$", ""):
        raise UnitError("ExecStart must escape every variable as $$ for systemd")
    words = shlex.split(script.replace("$$", "$"))
    if words[:4] != ["cd", "$LEONAID_CHECKOUT", "&&", "exec"]:
        raise UnitError("ExecStart must change into the checkout first")
    if words[4:6] != ["./leonaid", "pilot-backup"]:
        raise UnitError("ExecStart must run ./leonaid pilot-backup")
    arguments = words[6:]
    if len(arguments) % 2:
        raise UnitError("every pilot-backup option needs exactly one value")
    options = dict(zip(arguments[::2], arguments[1::2], strict=True))
    accepted, required = backup_options(root / "leonaid")
    if not set(options) <= accepted:
        raise UnitError(f"unknown pilot-backup options {set(options) - accepted}")
    if not required <= set(options):
        raise UnitError(f"missing pilot-backup options {required - set(options)}")
    referenced = set(re.findall(r"\$([A-Z_]+)", script.replace("$$", "$")))
    if referenced != set(environment):
        raise UnitError(
            "ExecStart variables and backup.env.example differ: "
            f"{sorted(referenced ^ set(environment))}"
        )
    for key, value in environment.items():
        if not value.startswith("/"):
            raise UnitError(f"backup.env.example {key} must be an absolute path")
    production = read_env(root / "infra/pilot/production.env.example")
    if (
        environment["LEONAID_BACKUP_MANIFEST"]
        != production["LEONAID_BACKUP_MANIFEST_PATH"]
    ):
        raise UnitError("pilot-backup requires the manifest path of production.env")

    schedule = timer.get("Timer", {})
    if not re.fullmatch(r"\*-\*-\* \d{2}:\d{2}:\d{2}", schedule.get("OnCalendar", "")):
        raise UnitError("the timer must run exactly once per day")
    if schedule.get("Persistent") != "true":
        raise UnitError("Persistent=true must catch up missed runs")
    if schedule.get("Unit") != "leonaid-backup.service":
        raise UnitError("the timer must start leonaid-backup.service")
    delay = time_span(schedule.get("RandomizedDelaySec", ""))
    if delay <= timedelta(0):
        raise UnitError("RandomizedDelaySec must spread the start time")
    if (
        timedelta(days=1) + delay + time_span(schedule["AccuracySec"])
        >= MAXIMUM_BACKUP_GAP
    ):
        raise UnitError("the worst-case gap between two backups exceeds 26 hours")
    if timer.get("Install", {}).get("WantedBy") != "timers.target":
        raise UnitError("the timer must be wanted by timers.target")


def rejected(root: Path, label: str, mutate: tuple[str, str, str]) -> None:
    """Prove the parser fails closed on one real file mutation."""

    name, old, new = mutate
    with tempfile.TemporaryDirectory() as directory:
        copy = Path(directory)
        for relative in (
            "infra/pilot/systemd",
            "infra/pilot/production.env.example",
            "leonaid",
        ):
            source = root / relative
            target = copy / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        unit = copy / "infra/pilot/systemd" / name
        text = unit.read_text(encoding="utf-8")
        if old not in text:
            raise AssertionError(f"mutation anchor missing: {label}")
        unit.write_text(text.replace(old, new, 1), encoding="utf-8")
        try:
            check(copy)
        except UnitError:
            return
    raise AssertionError(f"unsafe unit mutation was accepted: {label}")


def main() -> None:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    check(root)
    mutations = {
        "unknown option": (
            "leonaid-backup.service",
            "--credentials-file",
            "--credential-file",
        ),
        "missing password file": (
            "leonaid-backup.service",
            ' --password-file "$$LEONAID_RESTIC_PASSWORD_FILE"',
            "",
        ),
        "unescaped variable": (
            "leonaid-backup.service",
            '"$$LEONAID_ENV_FILE"',
            '"$LEONAID_ENV_FILE"',
        ),
        "root user": ("leonaid-backup.service", "User=leonaid", "User=root"),
        "private tmp": (
            "leonaid-backup.service",
            "NoNewPrivileges=yes",
            "NoNewPrivileges=yes\nPrivateTmp=yes",
        ),
        "no catch-up": (
            "leonaid-backup.timer",
            "\nPersistent=true\n",
            "\nPersistent=false\n",
        ),
        "weekly schedule": (
            "leonaid-backup.timer",
            "OnCalendar=*-*-* 02:30:00",
            "OnCalendar=Mon *-*-* 02:30:00",
        ),
        "gap over 26 hours": (
            "leonaid-backup.timer",
            "RandomizedDelaySec=45min",
            "RandomizedDelaySec=3h",
        ),
        "unknown variable": (
            "backup.env.example",
            "LEONAID_CHECKOUT=/opt/leonaid",
            "LEONAID_CHECKOUT=/opt/leonaid\nLEONAID_UNUSED=/tmp",
        ),
        "manifest drift": (
            "backup.env.example",
            "latest-backup-manifest.json",
            "other-manifest.json",
        ),
    }
    for label, mutation in mutations.items():
        rejected(root, label, mutation)
    print(
        "pilot-systemd-test: OK: backup service and timer match pilot-backup, "
        f"backup.env and the 26-hour window; {len(mutations)} unsafe mutations "
        "rejected"
    )


if __name__ == "__main__":
    main()
