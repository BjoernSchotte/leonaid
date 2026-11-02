#!/usr/bin/env python3
"""Capture and compare logical state across both databases and object storage."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

import asyncpg
import boto3


JsonObject = dict[str, Any]
CRITICAL_CORE_TABLES = {
    "acquisition_assignment",
    "audit_event",
    "charity_action",
    "commitment",
    "generated_document",
    "invoice",
    "outbox_event",
    "user_session",
}


class InventoryError(RuntimeError):
    """Recovered state is incomplete or differs from the checkpoint."""


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise InventoryError(f"Umgebungsvariable fehlt: {name}")
    return value


def digest_lines(lines: list[str]) -> str:
    payload = "\n".join(sorted(lines)).encode()
    return hashlib.sha256(payload).hexdigest()


def quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


async def unvalidated_foreign_keys(
    connection: asyncpg.Connection,
) -> list[JsonObject]:
    rows = await connection.fetch(
        """
        SELECT
            c.conname AS name,
            child_ns.nspname AS child_schema,
            child.relname AS child_table,
            parent_ns.nspname AS parent_schema,
            parent.relname AS parent_table,
            ARRAY(
                SELECT a.attname
                FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, position)
                JOIN pg_attribute a
                  ON a.attrelid = c.conrelid AND a.attnum = k.attnum
                ORDER BY k.position
            ) AS child_columns,
            ARRAY(
                SELECT a.attname
                FROM unnest(c.confkey) WITH ORDINALITY AS k(attnum, position)
                JOIN pg_attribute a
                  ON a.attrelid = c.confrelid AND a.attnum = k.attnum
                ORDER BY k.position
            ) AS parent_columns
        FROM pg_constraint c
        JOIN pg_class child ON child.oid = c.conrelid
        JOIN pg_namespace child_ns ON child_ns.oid = child.relnamespace
        JOIN pg_class parent ON parent.oid = c.confrelid
        JOIN pg_namespace parent_ns ON parent_ns.oid = parent.relnamespace
        WHERE c.contype = 'f' AND NOT c.convalidated
        ORDER BY child_ns.nspname, child.relname, c.conname
        """
    )
    return [
        {
            "name": str(row["name"]),
            "table": f"{row['child_schema']}.{row['child_table']}",
            "child": (str(row["child_schema"]), str(row["child_table"])),
            "parent": (str(row["parent_schema"]), str(row["parent_table"])),
            "childColumns": [str(column) for column in row["child_columns"]],
            "parentColumns": [str(column) for column in row["parent_columns"]],
        }
        for row in rows
    ]


async def require_foreign_key_holds(
    connection: asyncpg.Connection,
    constraint: JsonObject,
    *,
    label: str,
) -> None:
    """Prove a NOT VALID foreign key for every existing row (MATCH SIMPLE).

    Twenty 2.54 creates relation foreign keys NOT VALID and validates them in a
    deferred worker job. That job reads cached workspace metadata; when a
    relation field is created right after another one, the cache can still
    lack the new field, the job ends as "completed" without running
    VALIDATE CONSTRAINT, and the key stays NOT VALID for good. PostgreSQL
    still enforces such a key for every new or changed row, so only rows that
    existed before the key was added are unchecked. This query checks them.
    """
    child_schema, child_table = constraint["child"]
    parent_schema, parent_table = constraint["parent"]
    child_columns = constraint["childColumns"]
    parent_columns = constraint["parentColumns"]
    if not child_columns or len(child_columns) != len(parent_columns):
        raise InventoryError(
            f"{label}: Fremdschlüssel {constraint['name']} ist nicht lesbar"
        )
    not_null = " AND ".join(f"child.{quote(column)} IS NOT NULL" for column in child_columns)
    matches = " AND ".join(
        f"parent.{quote(parent_column)} = child.{quote(child_column)}"
        for child_column, parent_column in zip(child_columns, parent_columns)
    )
    violations = int(
        await connection.fetchval(
            f"SELECT count(*) FROM {quote(child_schema)}.{quote(child_table)} AS child "
            f"WHERE {not_null} AND NOT EXISTS ("
            f"SELECT 1 FROM {quote(parent_schema)}.{quote(parent_table)} AS parent "
            f"WHERE {matches})"
        )
        or 0
    )
    if violations:
        raise InventoryError(
            f"{label}: Fremdschlüssel {constraint['table']}.{constraint['name']} "
            f"ist nicht validiert und von {violations} Zeilen verletzt"
        )


async def database_inventory(url: str, *, label: str) -> JsonObject:
    connection = await asyncpg.connect(url, timeout=30)
    try:
        table_rows = await connection.fetch(
            """
            SELECT schemaname, tablename
            FROM pg_tables
            WHERE schemaname NOT IN (
                'information_schema', 'pg_catalog', 'pg_toast'
            )
              AND schemaname NOT LIKE 'pg_temp_%'
              AND schemaname NOT LIKE 'pg_toast_temp_%'
            ORDER BY schemaname, tablename
            """
        )
        tables: JsonObject = {}
        public_names: set[str] = set()
        for table in table_rows:
            schema = str(table["schemaname"])
            name = str(table["tablename"])
            rows = await connection.fetch(
                f"SELECT to_jsonb(item)::text AS value "
                f"FROM {quote(schema)}.{quote(name)} AS item"
            )
            values = [str(row["value"]) for row in rows]
            tables[f"{schema}.{name}"] = {
                "rows": len(values),
                "sha256": digest_lines(values),
            }
            if schema == "public":
                public_names.add(name)
        unvalidated = await unvalidated_foreign_keys(connection)
        if unvalidated and label != "twenty":
            raise InventoryError(
                f"{label}: {len(unvalidated)} Fremdschlüssel sind nicht validiert"
            )
        for constraint in unvalidated:
            await require_foreign_key_holds(connection, constraint, label=label)
        if label == "core":
            missing = sorted(CRITICAL_CORE_TABLES - public_names)
            if missing:
                raise InventoryError(f"Core-Kerntabellen fehlen: {missing}")
        return {
            "databaseSha256": digest_lines(
                [
                    f"{name}:{item['rows']}:{item['sha256']}"
                    for name, item in tables.items()
                ]
            ),
            "tableCount": len(tables),
            "tables": tables,
            "unvalidatedForeignKeys": len(unvalidated),
            "rowCheckedForeignKeys": sorted(
                f"{item['table']}.{item['name']}" for item in unvalidated
            ),
        }
    finally:
        await connection.close()


def file_inventory(root: Path) -> JsonObject:
    if not root.is_dir():
        raise InventoryError(f"Twenty-Dateiablage fehlt: {root}")
    files: list[JsonObject] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "kind": "symlink",
                    "target": os.readlink(path),
                }
            )
        elif path.is_file():
            content = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "kind": "file",
                    "size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
    return {
        "fileCount": len(files),
        "sha256": digest_lines(
            [json.dumps(item, sort_keys=True, separators=(",", ":")) for item in files]
        ),
        "files": files,
    }


async def object_inventory(core_url: str) -> JsonObject:
    client = boto3.client(
        "s3",
        endpoint_url=require_env("RUSTFS_ENDPOINT_URL"),
        aws_access_key_id=require_env("RUSTFS_ACCESS_KEY"),
        aws_secret_access_key=require_env("RUSTFS_SECRET_KEY"),
        region_name="us-east-1",
    )
    bucket = require_env("RUSTFS_BUCKET")
    listed = client.list_objects_v2(Bucket=bucket)
    objects: list[JsonObject] = []
    for item in listed.get("Contents", []):
        key = str(item["Key"])
        response = client.get_object(Bucket=bucket, Key=key)
        content = response["Body"].read()
        objects.append(
            {
                "key": key,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "versionId": response.get("VersionId"),
            }
        )

    connection = await asyncpg.connect(core_url, timeout=30)
    try:
        documents = await connection.fetch(
            """
            SELECT id, storage_bucket, object_key, storage_version_id, sha256
            FROM generated_document
            WHERE document_type = 'invoice_pdf' AND status = 'available'
            ORDER BY id
            """
        )
    finally:
        await connection.close()
    invoice_documents: list[JsonObject] = []
    for document in documents:
        response = client.get_object(
            Bucket=str(document["storage_bucket"]),
            Key=str(document["object_key"]),
            VersionId=str(document["storage_version_id"]),
        )
        content = response["Body"].read()
        actual = hashlib.sha256(content).hexdigest()
        stored = str(document["sha256"])
        if actual != stored:
            raise InventoryError(
                f"Rechnungs-PDF {document['id']} weicht von gespeichertem SHA-256 ab"
            )
        invoice_documents.append(
            {
                "id": str(document["id"]),
                "key": str(document["object_key"]),
                "sha256": actual,
                "versionId": str(document["storage_version_id"]),
            }
        )
    return {
        "bucket": bucket,
        "objectCount": len(objects),
        "objects": objects,
        "invoiceDocumentCount": len(invoice_documents),
        "invoiceDocuments": invoice_documents,
    }


async def capture(output: Path, twenty_storage: Path) -> None:
    core_url = require_env("CORE_DATABASE_URL")
    core = await database_inventory(core_url, label="core")
    twenty = await database_inventory(
        require_env("TWENTY_DATABASE_URL"),
        label="twenty",
    )
    rustfs = await object_inventory(core_url)
    value: JsonObject = {
        "schemaVersion": 1,
        "core": core,
        "twenty": twenty,
        "twentyStorage": file_inventory(twenty_storage),
        "rustfs": rustfs,
    }
    output.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "backup-inventory: OK: "
        f"{core['tableCount']} Core-Tabellen, "
        f"{twenty['tableCount']} Twenty-Tabellen, "
        f"{rustfs['objectCount']} RustFS-Objekte"
    )


def compare(before: Path, after: Path) -> None:
    left = json.loads(before.read_text(encoding="utf-8"))
    right = json.loads(after.read_text(encoding="utf-8"))
    if left != right:
        for key in ("core", "twenty", "twentyStorage", "rustfs"):
            if left.get(key) != right.get(key):
                raise InventoryError(f"Restore-Inventar weicht ab: {key}")
        raise InventoryError("Restore-Inventar weicht ab")
    print("backup-inventory: OK: Restore ist logisch und bytegenau identisch")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument("--output", required=True, type=Path)
    capture_parser.add_argument(
        "--twenty-storage",
        required=True,
        type=Path,
    )
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--before", required=True, type=Path)
    compare_parser.add_argument("--after", required=True, type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.command == "capture":
            asyncio.run(capture(arguments.output, arguments.twenty_storage))
        else:
            compare(arguments.before, arguments.after)
    except (OSError, ValueError, InventoryError, asyncpg.PostgresError) as error:
        print(f"backup-inventory: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
