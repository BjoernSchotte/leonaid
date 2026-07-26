#!/usr/bin/env python3
"""Seed, snapshot and deliberately mutate Golden Data through real systems."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import asyncpg
import boto3
import httpx
from botocore.exceptions import ClientError

DATASET_VERSION = "1.0.0"
OBJECT_PREFIX = "golden/v1/invoices/"
JsonObject = dict[str, Any]


class SeedError(RuntimeError):
    """A real target system rejected or lost Golden Data."""


def load_json_object(path: Path) -> JsonObject:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise SeedError(f"{path} muss ein JSON-Objekt enthalten")
    return value


def load_fixture(fixture: Path) -> tuple[JsonObject, JsonObject, str]:
    manifest = load_json_object(fixture / "manifest.json")
    dataset_bytes = (fixture / "dataset.json").read_bytes()
    dataset = json.loads(dataset_bytes)
    expected = load_json_object(fixture / "expected.json")
    if not isinstance(dataset, dict):
        raise SeedError("dataset.json muss ein JSON-Objekt enthalten")
    if manifest.get("datasetVersion") != DATASET_VERSION:
        raise SeedError("unerwartete Golden-Dataset-Version")
    return dataset, expected, hashlib.sha256(dataset_bytes).hexdigest()


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SeedError(f"erforderliche Umgebungsvariable fehlt: {name}")
    return value


def canonical_hash(value: JsonObject) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


class TwentyClient:
    """Narrow client for Twenty's supported GraphQL auth and REST Data APIs."""

    def __init__(self) -> None:
        self.base_url = require_env("TWENTY_BASE_URL").rstrip("/")
        self.origin = require_env("TWENTY_ORIGIN")
        self.email = require_env("TWENTY_BOOTSTRAP_EMAIL")
        self.password = require_env("TWENTY_BOOTSTRAP_PASSWORD")
        self.client = httpx.Client(timeout=180)
        self.access_token: str | None = None

    def close(self) -> None:
        self.client.close()

    def graphql(
        self,
        query: str,
        variables: JsonObject,
        *,
        bearer: str | None = None,
    ) -> JsonObject:
        headers = {"Origin": self.origin}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        response = self.client.post(
            f"{self.base_url}/metadata",
            json={"query": query, "variables": variables},
            headers=headers,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise SeedError("Twenty GraphQL lieferte kein JSON-Objekt")
        errors = payload.get("errors")
        if errors:
            messages = [
                str(item.get("message", "unbekannter GraphQL-Fehler"))
                for item in errors
                if isinstance(item, dict)
            ]
            raise SeedError(f"Twenty GraphQL: {'; '.join(messages)}")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise SeedError("Twenty GraphQL lieferte keine data")
        return data

    @staticmethod
    def token_from(value: Any, label: str) -> str:
        if not isinstance(value, dict):
            raise SeedError(f"Twenty {label} fehlt")
        token = value.get("token")
        if not isinstance(token, str) or not token:
            raise SeedError(f"Twenty {label}.token fehlt")
        return token

    def credentials_login_token(self) -> str:
        login = self.graphql(
            """
            mutation Login(
              $email: String!,
              $password: String!,
              $origin: String!
            ) {
              getLoginTokenFromCredentials(
                email: $email,
                password: $password,
                origin: $origin
              ) {
                loginToken { token }
              }
            }
            """,
            {
                "email": self.email,
                "password": self.password,
                "origin": self.origin,
            },
        )
        login_result = login.get("getLoginTokenFromCredentials")
        if not isinstance(login_result, dict):
            raise SeedError("Twenty Login-Response fehlt")
        return self.token_from(login_result.get("loginToken"), "loginToken")

    def exchange_login_token(self, login_token: str) -> str:
        exchanged = self.graphql(
            """
            mutation Exchange($loginToken: String!, $origin: String!) {
              getAuthTokensFromLoginToken(
                loginToken: $loginToken,
                origin: $origin
              ) {
                tokens {
                  accessOrWorkspaceAgnosticToken { token }
                }
              }
            }
            """,
            {"loginToken": login_token, "origin": self.origin},
        )
        exchange_result = exchanged.get("getAuthTokensFromLoginToken")
        if not isinstance(exchange_result, dict):
            raise SeedError("Twenty Token-Exchange-Response fehlt")
        exchange_tokens = exchange_result.get("tokens")
        if not isinstance(exchange_tokens, dict):
            raise SeedError("Twenty Access-Tokens fehlen")
        return self.token_from(
            exchange_tokens.get("accessOrWorkspaceAgnosticToken"),
            "accessToken",
        )

    def authenticate(self) -> None:
        check = self.graphql(
            """
            query CheckUser($email: String!) {
              checkUserExists(email: $email) { exists }
            }
            """,
            {"email": self.email},
        )
        user_state = check.get("checkUserExists")
        if not isinstance(user_state, dict):
            raise SeedError("Twenty checkUserExists fehlt")

        if user_state.get("exists") is True:
            login_token = self.credentials_login_token()
        else:
            signup = self.graphql(
                """
                mutation SignUp($email: String!, $password: String!) {
                  signUp(email: $email, password: $password) {
                    tokens {
                      accessOrWorkspaceAgnosticToken { token }
                    }
                  }
                }
                """,
                {"email": self.email, "password": self.password},
            )
            signup_result = signup.get("signUp")
            if not isinstance(signup_result, dict):
                raise SeedError("Twenty Sign-up-Response fehlt")
            tokens = signup_result.get("tokens")
            if not isinstance(tokens, dict):
                raise SeedError("Twenty Workspace-Agnostic-Tokens fehlen")
            user_token = self.token_from(
                tokens.get("accessOrWorkspaceAgnosticToken"),
                "workspaceAgnosticToken",
            )
            workspace = self.graphql(
                """
                mutation CreateWorkspace($input: SignUpInNewWorkspaceInput) {
                  signUpInNewWorkspace(input: $input) {
                    loginToken { token }
                    workspace { id }
                  }
                }
                """,
                {"input": {"displayName": "LeonAid Golden CRM"}},
                bearer=user_token,
            )
            workspace_result = workspace.get("signUpInNewWorkspace")
            if not isinstance(workspace_result, dict):
                raise SeedError("Twenty Workspace-Response fehlt")
            login_token = self.token_from(
                workspace_result.get("loginToken"),
                "loginToken",
            )

        self.access_token = self.exchange_login_token(login_token)
        activation = self.graphql(
            """
            mutation Activate($data: ActivateWorkspaceInput!) {
              activateWorkspace(data: $data) {
                id
                activationStatus
              }
            }
            """,
            {"data": {}},
            bearer=self.access_token,
        )
        if not isinstance(activation.get("activateWorkspace"), dict):
            raise SeedError("Twenty Workspace-Aktivierung fehlt")
        self.access_token = self.exchange_login_token(self.credentials_login_token())

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: JsonObject | None = None,
    ) -> httpx.Response:
        if self.access_token is None:
            raise SeedError("Twenty-Client ist nicht authentifiziert")
        return self.client.request(
            method,
            f"{self.base_url}{path}",
            headers={"Authorization": f"Bearer {self.access_token}"},
            json=json_body,
        )

    @staticmethod
    def response_data(response: httpx.Response) -> JsonObject:
        if response.is_error:
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = response.text[:500]
            raise SeedError(
                f"Twenty Data API HTTP {response.status_code}: {error_payload}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise SeedError("Twenty Data API lieferte kein JSON-Objekt")
        data = payload.get("data", payload)
        if not isinstance(data, dict):
            raise SeedError("Twenty Data API lieferte kein Objekt in data")
        if len(data) == 1:
            nested = next(iter(data.values()))
            if isinstance(nested, dict):
                return nested
        return data

    def get_record(self, collection: str, record_id: str) -> JsonObject | None:
        response = self.request("GET", f"/rest/{collection}/{record_id}")
        if response.status_code == 404:
            return None
        return self.response_data(response)

    def upsert(self, collection: str, record_id: str, fields: JsonObject) -> None:
        current = self.get_record(collection, record_id)
        if current is None:
            response = self.request(
                "POST",
                f"/rest/{collection}",
                json_body={"id": record_id, **fields},
            )
        else:
            response = self.request(
                "PATCH",
                f"/rest/{collection}/{record_id}",
                json_body=fields,
            )
        self.response_data(response)

    def wait_for_data_api(self) -> None:
        deadline = time.monotonic() + 120
        while True:
            response = self.request("GET", "/rest/companies?limit=1")
            if response.status_code == 200:
                return
            if response.status_code not in {400, 500, 502, 503, 504}:
                self.response_data(response)
            if time.monotonic() >= deadline:
                raise SeedError("Twenty Data API wurde nicht rechtzeitig bereit")
            time.sleep(1)


def company_fields(company: JsonObject) -> JsonObject:
    return {
        "name": company["name"],
        "address": {
            "addressCity": company["city"],
            "addressPostcode": company["postalCode"],
        },
    }


def person_fields(person: JsonObject) -> JsonObject:
    return {
        "name": {
            "firstName": person["givenName"],
            "lastName": person["familyName"],
        },
        "emails": {
            "primaryEmail": person["email"],
            "additionalEmails": [],
        },
        "companyId": person["companyId"],
    }


def seed_twenty(client: TwentyClient, dataset: JsonObject) -> None:
    client.authenticate()
    client.wait_for_data_api()
    for company in dataset["companies"]:
        client.upsert("companies", str(company["id"]), company_fields(company))
    for person in dataset["persons"]:
        client.upsert("people", str(person["id"]), person_fields(person))


def normalize_company(record: JsonObject) -> JsonObject:
    address = record.get("address")
    if not isinstance(address, dict):
        address = {}
    return {
        "id": record.get("id"),
        "name": record.get("name"),
        "postalCode": address.get("addressPostcode"),
        "city": address.get("addressCity"),
    }


def normalize_person(record: JsonObject) -> JsonObject:
    name = record.get("name")
    emails = record.get("emails")
    if not isinstance(name, dict):
        name = {}
    if not isinstance(emails, dict):
        emails = {}
    return {
        "id": record.get("id"),
        "givenName": name.get("firstName"),
        "familyName": name.get("lastName"),
        "email": emails.get("primaryEmail"),
        "companyId": record.get("companyId"),
    }


def snapshot_twenty(client: TwentyClient, dataset: JsonObject) -> JsonObject:
    client.authenticate()
    client.wait_for_data_api()
    companies: list[JsonObject] = []
    people: list[JsonObject] = []
    for expected in dataset["companies"]:
        record = client.get_record("companies", str(expected["id"]))
        companies.append(
            {"id": expected["id"], "missing": True}
            if record is None
            else normalize_company(record)
        )
    for expected in dataset["persons"]:
        record = client.get_record("people", str(expected["id"]))
        people.append(
            {"id": expected["id"], "missing": True}
            if record is None
            else normalize_person(record)
        )
    return {
        "companies": sorted(companies, key=lambda item: str(item["id"])),
        "people": sorted(people, key=lambda item: str(item["id"])),
    }


def expected_twenty(dataset: JsonObject) -> JsonObject:
    companies = [
        {
            "id": company["id"],
            "name": company["name"],
            "postalCode": company["postalCode"],
            "city": company["city"],
        }
        for company in dataset["companies"]
    ]
    people = [
        {
            "id": person["id"],
            "givenName": person["givenName"],
            "familyName": person["familyName"],
            "email": person["email"],
            "companyId": person["companyId"],
        }
        for person in dataset["persons"]
    ]
    return {
        "companies": sorted(companies, key=lambda item: str(item["id"])),
        "people": sorted(people, key=lambda item: str(item["id"])),
    }


def s3_client() -> Any:
    return boto3.client(
        "s3",
        endpoint_url=require_env("RUSTFS_ENDPOINT_URL"),
        aws_access_key_id=require_env("RUSTFS_ACCESS_KEY"),
        aws_secret_access_key=require_env("RUSTFS_SECRET_KEY"),
        region_name="us-east-1",
    )


def ensure_bucket(client: Any, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
        if status != 404:
            raise
        client.create_bucket(Bucket=bucket)


def load_pdf(path: Path) -> tuple[bytes, str]:
    content = path.read_bytes()
    if (
        len(content) < 1_000
        or not content.startswith(b"%PDF-")
        or b"%%EOF" not in content[-1_024:]
    ):
        raise SeedError(f"Typst-Artefakt ist kein vollständiges PDF: {path}")
    return content, hashlib.sha256(content).hexdigest()


def pdf_manifest(dataset: JsonObject, pdf_directory: Path) -> list[JsonObject]:
    manifest: list[JsonObject] = []
    for invoice in dataset["invoices"]:
        number = str(invoice["number"])
        path = pdf_directory / f"{number}.pdf"
        content, digest = load_pdf(path)
        manifest.append(
            {
                "invoiceId": invoice["id"],
                "invoiceNumber": number,
                "objectKey": f"{OBJECT_PREFIX}{number}.pdf",
                "sha256": digest,
                "size": len(content),
            }
        )
    return sorted(manifest, key=lambda item: str(item["invoiceId"]))


def seed_rustfs(dataset: JsonObject, pdf_directory: Path) -> list[JsonObject]:
    client = s3_client()
    bucket = require_env("RUSTFS_BUCKET")
    ensure_bucket(client, bucket)
    manifest = pdf_manifest(dataset, pdf_directory)
    expected_keys = {str(item["objectKey"]) for item in manifest}
    listed = client.list_objects_v2(Bucket=bucket, Prefix=OBJECT_PREFIX)
    for item in listed.get("Contents", []):
        key = item.get("Key")
        if isinstance(key, str) and key not in expected_keys:
            client.delete_object(Bucket=bucket, Key=key)
    for item in manifest:
        content = (pdf_directory / f"{item['invoiceNumber']}.pdf").read_bytes()
        client.put_object(
            Bucket=bucket,
            Key=item["objectKey"],
            Body=content,
            ContentType="application/pdf",
            Metadata={
                "sha256": item["sha256"],
                "dataset-version": DATASET_VERSION,
                "invoice-id": item["invoiceId"],
                "invoice-number": item["invoiceNumber"],
            },
        )
    return manifest


def snapshot_rustfs(dataset: JsonObject) -> JsonObject:
    client = s3_client()
    bucket = require_env("RUSTFS_BUCKET")
    objects: list[JsonObject] = []
    for invoice in dataset["invoices"]:
        key = f"{OBJECT_PREFIX}{invoice['number']}.pdf"
        try:
            response = client.get_object(Bucket=bucket, Key=key)
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                objects.append({"objectKey": key, "missing": True})
                continue
            raise
        content = response["Body"].read()
        metadata = response.get("Metadata", {})
        objects.append(
            {
                "invoiceId": invoice["id"],
                "invoiceNumber": invoice["number"],
                "objectKey": key,
                "sha256": hashlib.sha256(content).hexdigest(),
                "storedSha256": metadata.get("sha256"),
                "contentType": response.get("ContentType"),
                "size": len(content),
                "isPdf": content.startswith(b"%PDF-") and b"%%EOF" in content[-1_024:],
            }
        )
    return {"objects": sorted(objects, key=lambda item: str(item["objectKey"]))}


async def seed_core(
    dataset: JsonObject,
    expected: JsonObject,
    dataset_digest: str,
    documents: list[JsonObject],
) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await connection.execute(
            """
            CREATE TABLE IF NOT EXISTS golden_seed_snapshot (
                dataset_version text PRIMARY KEY,
                schema_version integer NOT NULL,
                dataset_sha256 char(64) NOT NULL,
                dataset_payload jsonb NOT NULL,
                expected_payload jsonb NOT NULL,
                document_manifest jsonb NOT NULL
            )
            """
        )
        await connection.execute(
            "DELETE FROM golden_seed_snapshot WHERE dataset_version <> $1",
            DATASET_VERSION,
        )
        await connection.execute(
            """
            INSERT INTO golden_seed_snapshot (
                dataset_version,
                schema_version,
                dataset_sha256,
                dataset_payload,
                expected_payload,
                document_manifest
            )
            VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb)
            ON CONFLICT (dataset_version) DO UPDATE
            SET schema_version = EXCLUDED.schema_version,
                dataset_sha256 = EXCLUDED.dataset_sha256,
                dataset_payload = EXCLUDED.dataset_payload,
                expected_payload = EXCLUDED.expected_payload,
                document_manifest = EXCLUDED.document_manifest
            """,
            DATASET_VERSION,
            int(dataset["schemaVersion"]),
            dataset_digest,
            json.dumps(dataset, ensure_ascii=False, separators=(",", ":")),
            json.dumps(expected, ensure_ascii=False, separators=(",", ":")),
            json.dumps(documents, ensure_ascii=False, separators=(",", ":")),
        )
    finally:
        await connection.close()


async def snapshot_core() -> JsonObject:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        count = await connection.fetchval("SELECT count(*) FROM golden_seed_snapshot")
        row = await connection.fetchrow(
            """
            SELECT
                schema_version,
                dataset_sha256,
                dataset_payload::text,
                expected_payload::text,
                document_manifest::text
            FROM golden_seed_snapshot
            WHERE dataset_version = $1
            """,
            DATASET_VERSION,
        )
    finally:
        await connection.close()
    if row is None:
        return {"rowCount": count, "missing": True}
    dataset = json.loads(row["dataset_payload"])
    expected = json.loads(row["expected_payload"])
    collections = {
        name: {
            "count": len(items),
            "ids": sorted(str(item["id"]) for item in items),
        }
        for name, items in dataset.items()
        if isinstance(items, list)
        and all(isinstance(item, dict) and "id" in item for item in items)
    }
    return {
        "rowCount": count,
        "schemaVersion": row["schema_version"],
        "datasetSha256": str(row["dataset_sha256"]).strip(),
        "collections": collections,
        "expectedCounts": expected.get("counts"),
        "documentManifest": json.loads(row["document_manifest"]),
    }


def mailpit_request(method: str, path: str) -> httpx.Response:
    response = httpx.request(
        method,
        f"{require_env('MAILPIT_API_URL').rstrip('/')}{path}",
        timeout=20,
    )
    response.raise_for_status()
    return response


def clear_mailpit() -> None:
    mailpit_request("DELETE", "/api/v1/messages")


def snapshot_mailpit() -> JsonObject:
    payload = mailpit_request("GET", "/api/v1/messages").json()
    if not isinstance(payload, dict):
        raise SeedError("Mailpit Messages API lieferte kein JSON-Objekt")
    messages = payload.get("messages")
    if not isinstance(messages, list):
        raise SeedError("Mailpit Messages API lieferte keine messages-Liste")
    return {
        "total": payload.get("total"),
        "messageIds": sorted(
            str(message.get("ID"))
            for message in messages
            if isinstance(message, dict) and message.get("ID") is not None
        ),
    }


async def seed(fixture: Path, pdf_directory: Path) -> JsonObject:
    dataset, expected, dataset_digest = load_fixture(fixture)
    twenty = TwentyClient()
    try:
        seed_twenty(twenty, dataset)
    finally:
        twenty.close()
    documents = seed_rustfs(dataset, pdf_directory)
    await seed_core(dataset, expected, dataset_digest, documents)
    clear_mailpit()
    value = await snapshot(fixture)
    verify_seed_snapshot(value, dataset, expected, dataset_digest, documents)
    return value


def verify_seed_snapshot(
    value: JsonObject,
    dataset: JsonObject,
    expected: JsonObject,
    dataset_digest: str,
    documents: list[JsonObject],
) -> None:
    core = value.get("core")
    if not isinstance(core, dict):
        raise SeedError("Core-Snapshot fehlt")
    if core.get("rowCount") != 1 or core.get("datasetSha256") != dataset_digest:
        raise SeedError("Core-PostgreSQL entspricht nicht Golden Data v1")
    if core.get("expectedCounts") != expected.get("counts"):
        raise SeedError("Core-PostgreSQL enthält unerwartete fachliche Counts")
    if core.get("documentManifest") != documents:
        raise SeedError("Core-Dokumentzuordnungen weichen vom PDF-Manifest ab")
    if value.get("twenty") != expected_twenty(dataset):
        raise SeedError("Twenty enthält nicht exakt die Golden-Firmen und -Kontakte")
    rustfs = value.get("rustfs")
    if not isinstance(rustfs, dict):
        raise SeedError("RustFS-Snapshot fehlt")
    objects = rustfs.get("objects")
    if not isinstance(objects, list) or len(objects) != len(documents):
        raise SeedError("RustFS enthält nicht exakt die Golden-PDFs")
    if any(
        not isinstance(item, dict)
        or item.get("isPdf") is not True
        or item.get("sha256") != item.get("storedSha256")
        for item in objects
    ):
        raise SeedError("RustFS-PDF oder gespeicherte SHA-256-Prüfsumme ist ungültig")
    if value.get("mailpit") != {"total": 0, "messageIds": []}:
        raise SeedError("Mailpit wurde nicht auf den leeren Golden-Stand gesetzt")


async def snapshot(fixture: Path) -> JsonObject:
    dataset, _expected, dataset_digest = load_fixture(fixture)
    twenty = TwentyClient()
    try:
        crm = snapshot_twenty(twenty, dataset)
    finally:
        twenty.close()
    value = {
        "datasetVersion": DATASET_VERSION,
        "expectedDatasetSha256": dataset_digest,
        "core": await snapshot_core(),
        "twenty": crm,
        "rustfs": snapshot_rustfs(dataset),
        "mailpit": snapshot_mailpit(),
    }
    value["snapshotSha256"] = canonical_hash(value)
    return value


async def mutate(fixture: Path) -> None:
    dataset, _expected, _digest = load_fixture(fixture)
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        await connection.execute(
            """
            UPDATE golden_seed_snapshot
            SET dataset_sha256 = $1
            WHERE dataset_version = $2
            """,
            "0" * 64,
            DATASET_VERSION,
        )
    finally:
        await connection.close()

    twenty = TwentyClient()
    try:
        twenty.authenticate()
        company = dataset["companies"][0]
        response = twenty.request(
            "PATCH",
            f"/rest/companies/{company['id']}",
            json_body={"name": "ABSICHTLICH MUTIERT"},
        )
        TwentyClient.response_data(response)
    finally:
        twenty.close()

    first_invoice = dataset["invoices"][0]
    content = b"%PDF-1.4\nabsichtlich mutiert\n%%EOF\n"
    s3_client().put_object(
        Bucket=require_env("RUSTFS_BUCKET"),
        Key=f"{OBJECT_PREFIX}{first_invoice['number']}.pdf",
        Body=content,
        ContentType="application/pdf",
        Metadata={"sha256": hashlib.sha256(content).hexdigest()},
    )

    message = EmailMessage()
    message["From"] = "mutation-test@leonaid.invalid"
    message["To"] = "reset-proof@leonaid.invalid"
    message["Subject"] = "Absichtliche POC-012-Mutation"
    message.set_content("Diese Nachricht muss durch Reset verschwinden.")
    with smtplib.SMTP(
        require_env("MAILPIT_SMTP_HOST"),
        int(require_env("MAILPIT_SMTP_PORT")),
        timeout=20,
    ) as smtp:
        smtp.send_message(message)


def write_snapshot(value: JsonObject, output: Path | None) -> None:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        sys.stdout.write(encoded)
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(encoded, encoding="utf-8")
    print(f"golden-snapshot: OK: {output} sha256={value['snapshotSha256']}")


async def run(arguments: argparse.Namespace) -> None:
    fixture = arguments.fixture.resolve()
    if arguments.command == "seed-twenty":
        dataset, _expected, _dataset_digest = load_fixture(fixture)
        twenty = TwentyClient()
        try:
            seed_twenty(twenty, dataset)
        finally:
            twenty.close()
        print("golden-seed-twenty: OK: Companies und People über Data API gesetzt")
    elif arguments.command == "seed":
        value = await seed(fixture, arguments.pdf_directory.resolve())
        print(
            "golden-seed: OK: "
            f"Dataset {DATASET_VERSION} sha256={value['snapshotSha256']}"
        )
    elif arguments.command == "snapshot":
        write_snapshot(await snapshot(fixture), arguments.output)
    else:
        await mutate(fixture)
        print("golden-mutate: OK: vier reale Systeme absichtlich verändert")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("seed", "seed-twenty", "snapshot", "mutate"):
        command = subparsers.add_parser(name)
        command.add_argument("fixture", type=Path)
        if name == "seed":
            command.add_argument("pdf_directory", type=Path)
        if name == "snapshot":
            command.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments))
    except (
        OSError,
        SeedError,
        asyncpg.PostgresError,
        httpx.HTTPError,
        ClientError,
    ) as error:
        print(f"golden-{arguments.command}: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
