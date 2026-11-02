#!/usr/bin/env python3
"""Vulnerability gate policy: scan scope, reviewed allowlist and report gate.

Subcommands (all paths are repository-relative to ROOT):

  check ROOT              validate scope and allowlist (offline, date-aware)
  targets ROOT            print one "<target>\t<mode>\t<reference>" line per
                          image the scanner must cover
  gate ROOT REPORTS       evaluate Trivy and OSV-Scanner JSON reports

Blocking means: HIGH or CRITICAL severity (CVSS >= 7.0 for OSV, unknown
severity counts as blocking) with a fixed version available. A finding is
waived only by an allowlist entry with a reason, a reviewer, a review date and
an expiry no more than MAX_WAIVER_DAYS after the review. Expired entries fail
every gate, so a waiver can never silently outlive its review.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ALLOWLIST = Path("infra/security/vulnerability-allowlist.json")
SCOPE = Path("infra/security/image-scan-scope.json")
LOCK = Path("infra/locks/external-systems.lock")
MAX_WAIVER_DAYS = 90
MIN_REASON_LENGTH = 40
BLOCKING_SEVERITIES = {"HIGH", "CRITICAL"}
VULN_ID = re.compile(r"^[A-Z][A-Z0-9]*-[A-Za-z0-9][A-Za-z0-9:._-]*$")
IMAGE_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
EXCLUSION_KINDS = {"toolchain", "base-image", "test-only", "upgrade-source"}
FS_TARGET = "fs"
OSV_TARGET = "osv"


class PolicyError(Exception):
    """Raised for unreadable or structurally invalid policy files."""


@dataclass(frozen=True)
class Target:
    name: str
    mode: str
    reference: str


@dataclass(frozen=True)
class Waiver:
    vuln_id: str
    targets: frozenset[str]
    reason: str
    reviewer: str
    reviewed_on: date
    expires: date


@dataclass(frozen=True)
class Finding:
    target: str
    vuln_ids: frozenset[str]
    package: str
    installed: str
    fixed: str
    severity: str

    @property
    def primary_id(self) -> str:
        return sorted(self.vuln_ids)[0]


@dataclass
class Problems:
    messages: list[str] = field(default_factory=list)

    def add(self, message: str) -> None:
        self.messages.append(message)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PolicyError(f"{path}: cannot read JSON: {error}") from error


def parse_date(value: object, label: str, problems: Problems) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        problems.add(f"{label} must be an ISO date (YYYY-MM-DD), got {value!r}")
        return None


def load_targets(root: Path, problems: Problems) -> list[Target]:
    """Return all scan targets and report scope/lock drift into problems."""
    scope = read_json(root / SCOPE)
    lock = read_json(root / LOCK)
    systems = {
        str(item.get("id")): str(item.get("image"))
        for item in lock.get("systems", [])
        if isinstance(item, dict)
    }
    runtime = scope.get("runtime")
    excluded = scope.get("excluded")
    own = scope.get("ownImages")
    if not isinstance(runtime, list) or not all(isinstance(x, str) for x in runtime):
        problems.add(f"{SCOPE}: runtime must be a list of system ids")
        runtime = []
    if not isinstance(excluded, dict):
        problems.add(f"{SCOPE}: excluded must be an object")
        excluded = {}
    if not isinstance(own, list) or not all(
        isinstance(x, str) and IMAGE_NAME.fullmatch(x) for x in own
    ):
        problems.add(f"{SCOPE}: ownImages must be a list of local image names")
        own = []

    for system_id, rule in excluded.items():
        if (
            not isinstance(rule, dict)
            or rule.get("kind") not in EXCLUSION_KINDS
            or len(str(rule.get("reason", "")).strip()) < MIN_REASON_LENGTH
        ):
            problems.add(
                f"{SCOPE}: excluded {system_id} needs kind in "
                f"{sorted(EXCLUSION_KINDS)} and a reason of at least "
                f"{MIN_REASON_LENGTH} characters"
            )
    overlap = set(runtime) & set(excluded)
    if overlap:
        problems.add(f"{SCOPE}: systems both scanned and excluded: {sorted(overlap)}")
    if len(set(runtime)) != len(runtime):
        problems.add(f"{SCOPE}: runtime lists a system twice")
    classified = set(runtime) | set(excluded)
    unclassified = sorted(set(systems) - classified)
    unknown = sorted(classified - set(systems))
    if unclassified:
        problems.add(
            f"{SCOPE}: lock systems without scan decision: {unclassified}; "
            "add each to runtime (scanned) or excluded (with kind and reason)"
        )
    if unknown:
        problems.add(f"{SCOPE}: systems not in {LOCK}: {unknown}")

    targets = [Target(FS_TARGET, "fs", "/workspace"), Target(OSV_TARGET, "osv", "")]
    targets += [Target(f"image:{name}", "local", f"{name}:latest") for name in own]
    targets += [
        Target(f"image:{system_id}", "remote", systems[system_id])
        for system_id in runtime
        if system_id in systems
    ]
    return targets


def load_waivers(
    root: Path, known_targets: set[str], today: date, problems: Problems
) -> list[Waiver]:
    data = read_json(root / ALLOWLIST)
    if not isinstance(data, dict) or data.get("schemaVersion") != 1:
        problems.add(f"{ALLOWLIST}: schemaVersion must be 1")
        return []
    entries = data.get("entries")
    if not isinstance(entries, list):
        problems.add(f"{ALLOWLIST}: entries must be a list")
        return []

    waivers: list[Waiver] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        label = f"{ALLOWLIST}: entries[{index}]"
        if not isinstance(entry, dict):
            problems.add(f"{label} must be an object")
            continue
        vuln_id = str(entry.get("id", ""))
        label = f"{label} ({vuln_id or 'no id'})"
        allowed = {"id", "targets", "reason", "reviewer", "reviewedOn", "expires"}
        if set(entry) != allowed:
            problems.add(f"{label} must have exactly the fields {sorted(allowed)}")
        if not VULN_ID.fullmatch(vuln_id):
            problems.add(f"{label}: id must be an advisory id like CVE-… or GHSA-…")
        reason = str(entry.get("reason", "")).strip()
        if len(reason) < MIN_REASON_LENGTH:
            problems.add(
                f"{label}: reason must explain the risk acceptance "
                f"(at least {MIN_REASON_LENGTH} characters)"
            )
        reviewer = str(entry.get("reviewer", "")).strip()
        if not reviewer:
            problems.add(f"{label}: reviewer is required")
        targets = entry.get("targets")
        if (
            not isinstance(targets, list)
            or not targets
            or not all(isinstance(t, str) for t in targets)
        ):
            problems.add(f"{label}: targets must be a non-empty list of strings")
            targets = []
        for target in targets:
            if target not in known_targets:
                problems.add(
                    f"{label}: unknown target {target!r}; "
                    f"known: {sorted(known_targets)}"
                )
            if (vuln_id, target) in seen:
                problems.add(f"{label}: duplicate waiver for {target}")
            seen.add((vuln_id, target))
        reviewed_on = parse_date(
            entry.get("reviewedOn"), f"{label}: reviewedOn", problems
        )
        expires = parse_date(entry.get("expires"), f"{label}: expires", problems)
        if reviewed_on is None or expires is None:
            continue
        if reviewed_on > today:
            problems.add(f"{label}: reviewedOn {reviewed_on} lies in the future")
        if expires < reviewed_on:
            problems.add(f"{label}: expires before it was reviewed")
        if expires - reviewed_on > timedelta(days=MAX_WAIVER_DAYS):
            problems.add(
                f"{label}: expires more than {MAX_WAIVER_DAYS} days after review; "
                "shorten the waiver and re-review it"
            )
        if expires < today:
            problems.add(
                f"{label}: waiver EXPIRED on {expires}. Re-check whether a fix is "
                "available now: upgrade and delete the entry, or re-review the "
                "risk and set reviewedOn to today and a new expires date"
            )
        waivers.append(
            Waiver(vuln_id, frozenset(targets), reason, reviewer, reviewed_on, expires)
        )
    return waivers


def check(root: Path, today: date) -> tuple[list[Target], list[Waiver], Problems]:
    problems = Problems()
    targets = load_targets(root, problems)
    waivers = load_waivers(root, {t.name for t in targets}, today, problems)
    return targets, waivers, problems


def cvss_score(value: object) -> float | None:
    try:
        return float(str(value))
    except ValueError:
        return None


def has_fix(vulnerability: dict[str, Any], package: str) -> bool:
    for affected in vulnerability.get("affected", []) or []:
        name = str((affected.get("package") or {}).get("name", ""))
        if name.lower() != package.lower():
            continue
        for range_ in affected.get("ranges", []) or []:
            if any("fixed" in event for event in range_.get("events", []) or []):
                return True
    return False


def osv_findings(report: Any) -> list[Finding]:
    findings: list[Finding] = []
    for result in report.get("results", []) or []:
        source = str((result.get("source") or {}).get("path", "?"))
        for package in result.get("packages", []) or []:
            info = package.get("package") or {}
            name = str(info.get("name", "?"))
            version = str(info.get("version", "?"))
            by_id = {
                str(v.get("id")): v for v in package.get("vulnerabilities", []) or []
            }
            for group in package.get("groups", []) or []:
                ids = [str(i) for i in group.get("ids", []) or []]
                aliases = {str(a) for a in group.get("aliases", []) or []}
                members = [by_id[i] for i in ids if i in by_id]
                score = cvss_score(group.get("max_severity", ""))
                labels = {
                    str((v.get("database_specific") or {}).get("severity", "")).upper()
                    for v in members
                } - {""}
                if score is not None:
                    severity = (
                        "CRITICAL" if score >= 9.0 else "HIGH" if score >= 7.0 else ""
                    )
                elif labels:
                    blocking = labels & BLOCKING_SEVERITIES
                    severity = sorted(blocking)[0] if blocking else ""
                else:
                    severity = "UNKNOWN"
                if not severity:
                    continue
                if not any(has_fix(v, name) for v in members):
                    continue
                findings.append(
                    Finding(
                        f"{OSV_TARGET}:{Path(source).name}",
                        frozenset(ids) | aliases,
                        name,
                        version,
                        "see advisory",
                        severity if score is None else f"{severity} {score}",
                    )
                )
    return findings


def trivy_findings(target: str, report: Any) -> list[Finding]:
    findings: list[Finding] = []
    for result in report.get("Results", []) or []:
        for vulnerability in result.get("Vulnerabilities", []) or []:
            severity = str(vulnerability.get("Severity", "")).upper()
            fixed = str(vulnerability.get("FixedVersion", "") or "")
            if severity not in BLOCKING_SEVERITIES or not fixed:
                continue
            ids = {str(vulnerability.get("VulnerabilityID", ""))}
            ids |= {str(v) for v in vulnerability.get("VendorIDs", []) or []}
            findings.append(
                Finding(
                    target,
                    frozenset(ids - {""}),
                    str(vulnerability.get("PkgName", "?")),
                    str(vulnerability.get("InstalledVersion", "?")),
                    fixed,
                    severity,
                )
            )
    return findings


def report_file(target: str) -> str:
    return target.replace(":", "--") + ".json"


def waiver_target(finding: Finding) -> str:
    # OSV findings are reported per lockfile but waived for the whole audit.
    return OSV_TARGET if finding.target.startswith(f"{OSV_TARGET}:") else finding.target


def gate(root: Path, reports: Path, today: date) -> int:
    targets, waivers, problems = check(root, today)
    findings: list[Finding] = []
    for target in targets:
        path = reports / report_file(target.name)
        try:
            report = read_json(path)
        except PolicyError as error:
            problems.add(
                f"missing or unreadable scan report for {target.name}: {error}"
            )
            continue
        if target.name == OSV_TARGET:
            findings += osv_findings(report)
        else:
            findings += trivy_findings(target.name, report)

    used: set[tuple[str, str]] = set()
    blocking: list[Finding] = []
    waived = 0
    for finding in findings:
        scope = waiver_target(finding)
        match = next(
            (
                w
                for w in waivers
                if w.vuln_id in finding.vuln_ids
                and scope in w.targets
                and w.expires >= today
            ),
            None,
        )
        if match is None:
            blocking.append(finding)
        else:
            waived += 1
            used.add((match.vuln_id, scope))

    for waiver in waivers:
        for waived_target in sorted(waiver.targets):
            if (waiver.vuln_id, waived_target) not in used:
                print(
                    f"vuln-gate: NOTE: waiver {waiver.vuln_id} for {waived_target} matched "
                    "nothing; delete it if the finding is fixed"
                )
    for message in problems.messages:
        print(f"vuln-gate: ERROR: {message}", file=sys.stderr)
    unique = sorted(
        {
            (f.target, f.primary_id, f.package, f.installed, f.fixed, f.severity)
            for f in blocking
        }
    )
    for finding_target, vuln_id, package, installed, fixed, severity in unique:
        print(
            f"vuln-gate: BLOCKING {finding_target}: {vuln_id} {severity} "
            f"{package} {installed} -> fixed in {fixed}",
            file=sys.stderr,
        )
    if problems.messages or unique:
        print(
            f"vuln-gate: FAILED: {len(unique)} fixable HIGH/CRITICAL finding(s), "
            f"{len(problems.messages)} policy error(s). Upgrade the dependency or "
            f"add a reviewed waiver to {ALLOWLIST}.",
            file=sys.stderr,
        )
        return 1
    print(
        f"vuln-gate: OK: {len(targets)} targets, no unwaived fixable HIGH/CRITICAL "
        f"finding ({waived} waived)"
    )
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 3 or argv[1] not in {"check", "targets", "gate"}:
        print(__doc__, file=sys.stderr)
        return 64
    root = Path(argv[2]).resolve()
    today = date.today()
    try:
        if argv[1] == "gate":
            if len(argv) != 4:
                print("usage: vuln_policy.py gate ROOT REPORTS", file=sys.stderr)
                return 64
            return gate(root, Path(argv[3]), today)
        targets, waivers, problems = check(root, today)
    except PolicyError as error:
        print(f"vuln-policy: ERROR: {error}", file=sys.stderr)
        return 1
    for message in problems.messages:
        print(f"vuln-policy: ERROR: {message}", file=sys.stderr)
    if problems.messages:
        return 1
    if argv[1] == "targets":
        for target in targets:
            print(f"{target.name}\t{target.mode}\t{target.reference}")
        return 0
    print(
        f"vuln-policy: OK: {len(targets)} scan targets classified, "
        f"{len(waivers)} reviewed waiver(s) valid"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
