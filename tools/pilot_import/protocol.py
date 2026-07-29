#!/usr/bin/env python3
"""Dry-run-first protocol around a one-off, agent-authored pilot import."""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal, cast

from pydantic import SecretStr

from leonaid.adapters.twenty.gateway import TwentyCrmGateway, TwentyGatewaySettings
from leonaid.application.crm import CrmGatewayError
from tools.backup.manifest import ManifestError, verify as verify_backup_manifest
from tools.twenty.import_contacts import (
    ContactImporter,
    ImportFailure,
    ImportMode,
    RowPlan,
    RowStatus,
    load_mapping,
    load_resolutions,
    load_rows,
    sha256_file,
)

JsonObject = dict[str, Any]
Command = Literal["dry-run", "apply", "verify"]
OPAQUE_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+$")
ENVIRONMENT = re.compile(r"^(?:staging|production)-[a-z0-9][a-z0-9-]{1,62}$")


class PilotImportFailure(RuntimeError):
    """A stable, operator-actionable pilot import rejection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ImportContext:
    root: Path
    command: Command
    batch_id: str
    target_environment: str
    source: Path
    manifest: Path
    mapping: Path
    resolutions: Path | None
    report: Path
    summary: Path | None
    sheet: str
    approval: Path | None
    backup_manifest: Path | None


def require_object(path: Path, *, label: str) -> JsonObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PilotImportFailure(
            f"{label.upper()}_INVALID",
            f"{label} ist nicht als JSON lesbar",
        ) from error
    if not isinstance(value, dict):
        raise PilotImportFailure(
            f"{label.upper()}_INVALID",
            f"{label} muss ein JSON-Objekt sein",
        )
    return value


def require_opaque(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not OPAQUE_ID.fullmatch(value):
        raise PilotImportFailure(
            "MANIFEST_METADATA_INVALID",
            f"{label} muss eine opake ID besitzen",
        )
    return value


def require_timestamp(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise PilotImportFailure(
            "MANIFEST_METADATA_INVALID",
            f"{label} muss ein ISO-8601-Zeitpunkt sein",
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise PilotImportFailure(
            "MANIFEST_METADATA_INVALID",
            f"{label} muss ein ISO-8601-Zeitpunkt sein",
        ) from error
    if parsed.tzinfo is None:
        raise PilotImportFailure(
            "MANIFEST_METADATA_INVALID",
            f"{label} benötigt eine Zeitzone",
        )
    return value


def ensure_private_file(path: Path, *, root: Path, area: str) -> None:
    expected_root = (root / ".local" / "pilot" / area).resolve()
    try:
        path.relative_to(expected_root)
    except ValueError as error:
        raise PilotImportFailure(
            "PRIVATE_PATH_REQUIRED",
            f"Datei muss unter .local/pilot/{area}/ liegen",
        ) from error
    if not path.is_file():
        raise PilotImportFailure("PRIVATE_FILE_MISSING", "private Datei fehlt")
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise PilotImportFailure(
            "PRIVATE_FILE_MODE_INVALID",
            "private Datei muss Modus 0600 besitzen",
        )


def ensure_private_output(path: Path, *, root: Path, area: str) -> None:
    expected_root = (root / ".local" / "pilot" / area).resolve()
    try:
        path.relative_to(expected_root)
    except ValueError as error:
        raise PilotImportFailure(
            "PRIVATE_PATH_REQUIRED",
            f"Ausgabe muss unter .local/pilot/{area}/ liegen",
        ) from error
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.parent.chmod(0o700)


def validate_intake_manifest(context: ImportContext) -> JsonObject:
    ensure_private_file(context.source, root=context.root, area="intake")
    ensure_private_file(context.manifest, root=context.root, area="manifests")
    payload = require_object(context.manifest, label="intake_manifest")
    if payload.get("schemaVersion") != 1:
        raise PilotImportFailure(
            "INTAKE_MANIFEST_VERSION_INVALID",
            "Intake-Manifest benötigt schemaVersion 1",
        )
    expected_sha = payload.get("sourceSha256")
    actual_sha = sha256_file(context.source)
    if expected_sha != actual_sha:
        raise PilotImportFailure(
            "SOURCE_FINGERPRINT_MISMATCH",
            "Quelldatei stimmt nicht mit dem Intake-Manifest überein",
        )
    if payload.get("purpose") != "historic-sponsor-contact-import":
        raise PilotImportFailure(
            "IMPORT_PURPOSE_INVALID",
            "Intake-Manifest ist nicht für den historischen Kontaktimport freigegeben",
        )
    require_opaque(
        payload.get("authorizationReference"), label="authorizationReference"
    )
    require_opaque(payload.get("responsibleActorId"), label="responsibleActorId")
    require_opaque(payload.get("externalEvidenceId"), label="externalEvidenceId")
    require_timestamp(payload.get("receivedAt"), label="receivedAt")
    return payload


def canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def atomic_private_json(path: Path, payload: JsonObject) -> None:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(encoded)
            target.flush()
            os.fsync(target.fileno())
        temporary.replace(path)
        path.chmod(0o600)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise PilotImportFailure(
            "TARGET_CONFIGURATION_MISSING",
            f"erforderliche Zielkonfiguration fehlt: {name}",
        )
    return value


def plans_json(plans: list[RowPlan]) -> list[JsonObject]:
    return [plan.to_json() for plan in plans]


def report_payload(
    context: ImportContext,
    *,
    command: Command,
    plans: list[RowPlan],
    applied: bool,
) -> JsonObject:
    serialized_plans = plans_json(plans)
    counts = Counter(plan.status.value for plan in plans)
    identity = {
        "batchId": context.batch_id,
        "targetEnvironment": context.target_environment,
        "sourceSha256": sha256_file(context.source),
        "mappingSha256": sha256_file(context.mapping),
        "resolutionSha256": (
            sha256_file(context.resolutions)
            if context.resolutions is not None
            else None
        ),
        "sheet": context.sheet,
        "rows": serialized_plans,
    }
    return {
        "schemaVersion": "leonaid.pilot-import-report/v1",
        "command": command,
        **identity,
        "planFingerprint": canonical_sha256(identity),
        "summary": {status.value: counts[status.value] for status in RowStatus},
        "appliedCount": sum(1 for plan in plans if plan.applied),
        "applied": applied,
    }


def sanitized_summary(report: JsonObject) -> JsonObject:
    return {
        "schemaVersion": "leonaid.pilot-import-summary/v1",
        "batchId": report["batchId"],
        "targetEnvironment": report["targetEnvironment"],
        "sourceSha256": report["sourceSha256"],
        "mappingSha256": report["mappingSha256"],
        "resolutionSha256": report["resolutionSha256"],
        "planFingerprint": report["planFingerprint"],
        "summary": report["summary"],
        "appliedCount": report["appliedCount"],
        "applied": report["applied"],
    }


def validate_context(arguments: argparse.Namespace) -> ImportContext:
    root = arguments.root.resolve()
    command = cast(Command, arguments.command)
    batch_id = require_opaque(arguments.batch_id, label="batch-id")
    if not ENVIRONMENT.fullmatch(arguments.target_environment):
        raise PilotImportFailure(
            "TARGET_ENVIRONMENT_INVALID",
            "target-environment muss staging-* oder production-* sein",
        )
    source = arguments.source.resolve()
    manifest = arguments.manifest.resolve()
    mapping = arguments.mapping.resolve()
    resolutions = (
        arguments.resolutions.resolve() if arguments.resolutions is not None else None
    )
    report = arguments.report.resolve()
    summary = arguments.summary.resolve() if arguments.summary is not None else None
    approval = arguments.approval.resolve() if arguments.approval is not None else None
    backup_manifest = (
        arguments.backup_manifest.resolve()
        if arguments.backup_manifest is not None
        else None
    )
    ensure_private_output(report, root=root, area="evidence")
    if summary is not None:
        ensure_private_output(summary, root=root, area="evidence")
    if resolutions is not None:
        ensure_private_file(resolutions, root=root, area="manifests")
    if approval is not None:
        ensure_private_file(approval, root=root, area="manifests")
    if backup_manifest is not None:
        ensure_private_file(backup_manifest, root=root, area="backups")
    return ImportContext(
        root=root,
        command=command,
        batch_id=batch_id,
        target_environment=arguments.target_environment,
        source=source,
        manifest=manifest,
        mapping=mapping,
        resolutions=resolutions,
        report=report,
        summary=summary,
        sheet=arguments.sheet,
        approval=approval,
        backup_manifest=backup_manifest,
    )


async def build_plans(
    context: ImportContext,
    *,
    mode: ImportMode,
) -> list[RowPlan]:
    mapping = load_mapping(context.mapping)
    rows = load_rows(context.source, context.sheet, mapping)
    resolutions = load_resolutions(context.resolutions)
    row_source_ids = {str(row.source_id) for row in rows if row.source_id is not None}
    if set(resolutions) - row_source_ids:
        raise PilotImportFailure(
            "STALE_RESOLUTION",
            "Resolution-Datei enthält Source-IDs außerhalb der Quelldatei",
        )
    settings = TwentyGatewaySettings(
        base_url=require_env("TWENTY_BASE_URL"),
        api_key=SecretStr(require_env("TWENTY_INTEGRATION_API_KEY")),
        timeout_seconds=5,
        page_size=20,
    )
    async with TwentyCrmGateway(settings) as gateway:
        importer = ContactImporter(
            gateway,
            mode=mode,
            resolutions=resolutions,
        )
        return [await importer.process(row) for row in rows]


def validate_approval(context: ImportContext, report: JsonObject) -> None:
    if context.approval is None or context.backup_manifest is None:
        raise PilotImportFailure(
            "APPLY_PREREQUISITE_MISSING",
            "Apply benötigt --approval und --backup-manifest",
        )
    backup_payload = require_object(context.backup_manifest, label="backup_manifest")
    source_project = backup_payload.get("sourceProject")
    if not isinstance(source_project, str) or not source_project:
        raise PilotImportFailure(
            "RECOVERY_POINT_INVALID",
            "Recovery Point enthält kein sourceProject",
        )
    if source_project != f"leonaid-{context.target_environment}":
        raise PilotImportFailure(
            "RECOVERY_POINT_TARGET_MISMATCH",
            "Recovery Point gehört nicht zur bestätigten Zielumgebung",
        )
    try:
        verify_backup_manifest(
            context.backup_manifest.parent,
            source_project=source_project,
        )
    except ManifestError as error:
        raise PilotImportFailure(
            "RECOVERY_POINT_INVALID",
            "Recovery Point ist unvollständig oder nicht bytegenau",
        ) from error
    approval = require_object(context.approval, label="approval")
    if approval.get("schemaVersion") != 1:
        raise PilotImportFailure(
            "APPROVAL_VERSION_INVALID",
            "Freigabe benötigt schemaVersion 1",
        )
    expected = {
        "batchId": context.batch_id,
        "targetEnvironment": context.target_environment,
        "planFingerprint": report["planFingerprint"],
        "sourceSha256": report["sourceSha256"],
        "mappingSha256": report["mappingSha256"],
        "resolutionSha256": report["resolutionSha256"],
        "backupManifestSha256": sha256_file(context.backup_manifest),
    }
    if any(approval.get(key) != value for key, value in expected.items()):
        raise PilotImportFailure(
            "APPROVAL_FINGERPRINT_MISMATCH",
            "Freigabe bindet nicht exakt Input, Mapping, Resolution, Plan und Recovery Point",
        )
    approvers = approval.get("approvedBy")
    if (
        not isinstance(approvers, list)
        or len(set(map(str, approvers))) < 2
        or not all(
            isinstance(item, str) and OPAQUE_ID.fullmatch(item) for item in approvers
        )
    ):
        raise PilotImportFailure(
            "FOUR_EYES_APPROVAL_MISSING",
            "Apply benötigt zwei unterschiedliche opake Freigabe-IDs",
        )
    require_timestamp(approval.get("approvedAt"), label="approvedAt")
    require_opaque(approval.get("recoveryPointId"), label="recoveryPointId")


@contextmanager
def exclusive_batch_lock(context: ImportContext) -> Iterator[None]:
    lock_root = context.root / ".local" / "pilot" / "manifests"
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_root.chmod(0o700)
    lock_path = lock_root / f".{context.batch_id}.apply.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        lock_path.chmod(0o600)
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise PilotImportFailure(
                "BATCH_APPLY_CONCURRENT",
                "dieser Importbatch wird bereits angewendet",
            ) from error
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def write_outputs(context: ImportContext, report: JsonObject) -> None:
    atomic_private_json(context.report, report)
    if context.summary is not None:
        atomic_private_json(context.summary, sanitized_summary(report))


async def execute(context: ImportContext) -> None:
    validate_intake_manifest(context)
    load_mapping(context.mapping)
    if context.resolutions is not None:
        load_resolutions(context.resolutions)

    if context.command == "dry-run":
        plans = await build_plans(context, mode="dry-run")
        report = report_payload(
            context,
            command="dry-run",
            plans=plans,
            applied=False,
        )
        write_outputs(context, report)
        return

    if context.command == "verify":
        plans = await build_plans(context, mode="dry-run")
        if any(
            plan.status in {RowStatus.NEW, RowStatus.UPDATE, RowStatus.CONFLICT}
            for plan in plans
        ):
            raise PilotImportFailure(
                "VERIFY_NOT_IDEMPOTENT",
                "Verify meldet neue, geänderte oder ungeklärte Datensätze",
            )
        report = report_payload(
            context,
            command="verify",
            plans=plans,
            applied=False,
        )
        write_outputs(context, report)
        return

    with exclusive_batch_lock(context):
        preflight = await build_plans(context, mode="dry-run")
        if any(plan.status is RowStatus.CONFLICT for plan in preflight):
            raise PilotImportFailure(
                "UNRESOLVED_CONFLICT",
                "Apply wird wegen ungeklärter Konflikte abgewiesen",
            )
        preflight_report = report_payload(
            context,
            command="dry-run",
            plans=preflight,
            applied=False,
        )
        validate_approval(context, preflight_report)
        applied_plans = await build_plans(context, mode="apply")
        report = report_payload(
            context,
            command="apply",
            plans=applied_plans,
            applied=True,
        )
        write_outputs(context, report)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description=(
            "Fail-closed one-off pilot import. Private source, metadata, reports, "
            "approval and recovery point remain below .local/pilot/."
        )
    )
    subparsers = result.add_subparsers(dest="command", required=True)
    for command in ("dry-run", "apply", "verify"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("source", type=Path)
        command_parser.add_argument("--root", type=Path, default=Path.cwd())
        command_parser.add_argument(
            "--env-file",
            type=Path,
            help="Consumed by the shell wrapper; accepted here for reproducible CLI.",
        )
        command_parser.add_argument("--batch-id", required=True)
        command_parser.add_argument("--target-environment", required=True)
        command_parser.add_argument("--manifest", type=Path, required=True)
        command_parser.add_argument("--mapping", type=Path, required=True)
        command_parser.add_argument("--resolutions", type=Path)
        command_parser.add_argument("--sheet", required=True)
        command_parser.add_argument("--report", type=Path, required=True)
        command_parser.add_argument("--summary", type=Path)
        command_parser.add_argument("--approval", type=Path)
        command_parser.add_argument("--backup-manifest", type=Path)
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        context = validate_context(arguments)
        asyncio.run(execute(context))
    except (
        CrmGatewayError,
        ImportFailure,
        ManifestError,
        PilotImportFailure,
        OSError,
    ) as error:
        code = (
            error.code
            if isinstance(error, PilotImportFailure)
            else "PILOT_IMPORT_FAILED"
        )
        print(f"pilot-import: ERROR [{code}]: {error}", file=sys.stderr)
        return 1
    print(
        f"pilot-import: OK: {arguments.command} batch={arguments.batch_id} "
        f"target={arguments.target_environment}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
