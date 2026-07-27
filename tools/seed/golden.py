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
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import boto3
import httpx
from botocore.exceptions import ClientError

from leonaid.adapters.typst import RENDER_VERSION

DATASET_VERSION = "1.0.0"
OBJECT_PREFIX = "golden/v1/invoices/"
ASSIGNMENT_HISTORY_NAMESPACE = UUID("c79fe114-6758-4dcb-a049-4dc7b353a920")
PUBLIC_ORDER_NAMESPACE = UUID("2cfebf83-5796-49d7-8c56-8dcb224f45ed")
GOLDEN_ASSIGNMENT_CHANGED_AT = datetime(
    2026,
    7,
    1,
    8,
    0,
    tzinfo=timezone.utc,
)
GOLDEN_COMMITMENT_CREATED_AT = datetime(
    2026,
    7,
    2,
    8,
    0,
    tzinfo=timezone.utc,
)
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
    client.put_bucket_versioning(
        Bucket=bucket,
        VersioningConfiguration={"Status": "Enabled"},
    )
    if client.get_bucket_versioning(Bucket=bucket).get("Status") != "Enabled":
        raise SeedError("S3-Bucket bestätigt keine aktive Versionierung")


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
        response = client.put_object(
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
        version_id = response.get("VersionId")
        if not isinstance(version_id, str) or version_id in {"", "null"}:
            raise SeedError("RustFS lieferte keine unveränderliche Version-ID")
        item["storageVersionId"] = version_id
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
                "storageVersionId": response.get("VersionId"),
                "size": len(content),
                "isPdf": content.startswith(b"%PDF-") and b"%%EOF" in content[-1_024:],
            }
        )
    return {"objects": sorted(objects, key=lambda item: str(item["objectKey"]))}


async def seed_identity(
    connection: asyncpg.Connection[Any],
    dataset: JsonObject,
) -> None:
    action_status = {
        "DRAFT": "draft",
        "SCHEDULED": "scheduled",
        "ACTIVE": "active",
        "COMPLETED": "completed",
        "ARCHIVED": "archived",
    }
    account_status = {
        "INVITED": "invited",
        "ACTIVE": "active",
        "LOCKED": "suspended",
        "ARCHIVED": "archived",
    }
    membership_role = {
        "CHARITY_ADMIN": "charity_admin",
        "ACQUIRER": "acquirer",
        "FINANCE": "finance_reader",
        "DRIVER": "driver",
    }

    for action in dataset["actions"]:
        goal_value = Decimal(int(action["goalAmountCents"])) / Decimal(100)
        actual_value = Decimal(int(action["actualAmountCents"])) / Decimal(100)
        await connection.execute(
            """
            INSERT INTO charity_action (
                id,
                carrier_name,
                name,
                purpose,
                status,
                starts_on,
                ends_on,
                publication_starts_at,
                publication_ends_at,
                archive_slug,
                goal_value,
                actual_value,
                goal_unit,
                currency
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7,
                $8, $9, $10, $11, $12, $13, $14
            )
            ON CONFLICT (id) DO UPDATE
            SET carrier_name = EXCLUDED.carrier_name,
                name = EXCLUDED.name,
                purpose = EXCLUDED.purpose,
                status = EXCLUDED.status,
                starts_on = EXCLUDED.starts_on,
                ends_on = EXCLUDED.ends_on,
                publication_starts_at = EXCLUDED.publication_starts_at,
                publication_ends_at = EXCLUDED.publication_ends_at,
                archive_slug = EXCLUDED.archive_slug,
                goal_value = EXCLUDED.goal_value,
                actual_value = EXCLUDED.actual_value,
                goal_unit = EXCLUDED.goal_unit,
                currency = EXCLUDED.currency,
                updated_at = CURRENT_TIMESTAMP
            """,
            action["id"],
            "Lions Club LeonAid Golden",
            action["name"],
            f"Synthetische Golden-Data-Aktion {action['kind']}",
            action_status[str(action["status"])],
            date.fromisoformat(str(action["startsOn"])),
            date.fromisoformat(str(action["endsOn"])),
            (
                datetime.fromisoformat(str(action["publicationStartsAt"]))
                if action["publicationStartsAt"] is not None
                else None
            ),
            (
                datetime.fromisoformat(str(action["publicationEndsAt"]))
                if action["publicationEndsAt"] is not None
                else None
            ),
            action["archiveSlug"],
            goal_value,
            actual_value,
            action["goalUnit"],
            action["currency"],
        )

    golden_action_ids = [action["id"] for action in dataset["actions"]]
    await connection.execute(
        "DELETE FROM charity_action_capability WHERE action_id = ANY($1::uuid[])",
        golden_action_ids,
    )
    for action in dataset["actions"]:
        await connection.executemany(
            """
            INSERT INTO charity_action_capability (action_id, capability)
            VALUES ($1, $2)
            """,
            [(action["id"], capability) for capability in action["capabilities"]],
        )

    await connection.execute(
        "DELETE FROM beneficiary WHERE action_id = ANY($1::uuid[])",
        golden_action_ids,
    )
    beneficiary_groups: dict[str, list[JsonObject]] = {}
    for beneficiary in dataset["beneficiaries"]:
        beneficiary_groups.setdefault(str(beneficiary["actionId"]), []).append(
            beneficiary
        )
    for action_id, beneficiaries in beneficiary_groups.items():
        await connection.executemany(
            """
            INSERT INTO beneficiary (
                id, action_id, organization_name, public_description, sort_order
            )
            VALUES ($1, $2, $3, $4, $5)
            """,
            [
                (
                    beneficiary["id"],
                    action_id,
                    beneficiary["name"],
                    beneficiary["description"],
                    index,
                )
                for index, beneficiary in enumerate(beneficiaries)
            ],
        )

    for user in dataset["users"]:
        await connection.execute(
            """
            INSERT INTO user_account (id, email, display_name, status)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (id) DO UPDATE
            SET display_name = EXCLUDED.display_name,
                status = EXCLUDED.status,
                updated_at = CURRENT_TIMESTAMP
            """,
            user["id"],
            str(user["email"]).casefold(),
            f"{user['givenName']} {user['familyName']}",
            account_status[str(user["status"])],
        )

    golden_user_ids = [user["id"] for user in dataset["users"]]
    await connection.execute(
        "DELETE FROM user_global_role WHERE user_id = ANY($1::uuid[])",
        golden_user_ids,
    )
    for user in dataset["users"]:
        if user["role"] == "SYSTEM_ADMIN":
            await connection.execute(
                """
                INSERT INTO user_global_role (user_id, role)
                VALUES ($1, 'system_admin')
                """,
                user["id"],
            )

    golden_membership_ids = [
        membership["id"] for membership in dataset["actionMemberships"]
    ]
    await connection.execute(
        "DELETE FROM action_membership WHERE id = ANY($1::uuid[])",
        golden_membership_ids,
    )
    for membership in dataset["actionMemberships"]:
        await connection.execute(
            """
            INSERT INTO action_membership (id, action_id, user_id, role)
            VALUES ($1, $2, $3, $4)
            """,
            membership["id"],
            membership["actionId"],
            membership["userId"],
            membership_role[str(membership["role"])],
        )

    await connection.execute(
        "DELETE FROM public_action_alias WHERE action_id = ANY($1::uuid[])",
        golden_action_ids,
    )
    for action in dataset["actions"]:
        if action["publicAlias"] is not None:
            await connection.execute(
                """
                INSERT INTO public_action_alias (alias, action_id)
                VALUES ($1, $2)
                ON CONFLICT (alias) DO UPDATE
                SET action_id = EXCLUDED.action_id,
                    switched_at = CURRENT_TIMESTAMP
                """,
                action["publicAlias"],
                action["id"],
            )

    current_action = next(
        action
        for action in dataset["actions"]
        if action["publicAlias"] == "krapfentaxi"
    )
    current_action_id = str(current_action["id"])
    form_id = uuid5(PUBLIC_ORDER_NAMESPACE, f"{current_action_id}:order-form")
    await connection.execute(
        "DELETE FROM order_form_configuration WHERE action_id = $1",
        current_action_id,
    )
    await connection.execute(
        "DELETE FROM action_template_snapshot WHERE action_id = $1",
        current_action_id,
    )
    snapshot = {
        "capabilities": current_action["capabilities"],
        "offerings": [
            {
                "code": "krapfenbox-24",
                "name": "Krapfenbox",
                "status": "active",
                "unit": "box",
                "piecesPerUnit": 24,
                "unitPriceMinor": 3600,
                "currency": "EUR",
            }
        ],
        "orderForm": {
            "formKey": "sponsor-bestellung",
            "title": "Krapfenboxen bestellen",
            "introduction": (
                "Bestellen Sie Krapfenboxen und unterstützen Sie die "
                "Begünstigten dieser Charity-Aktion."
            ),
            "submitLabel": "Bestellung verbindlich absenden",
            "requireCompanyName": False,
            "requireContactName": True,
            "requireEmail": True,
            "requirePhone": False,
            "requireDeliveryAddress": True,
            "requireBillingAddress": True,
            "allowMessage": True,
        },
    }
    await connection.execute(
        """
        INSERT INTO action_template_snapshot (
            action_id, template_key, template_version, display_name,
            copied_from_action_id, configuration
        )
        VALUES ($1, 'krapfentaxi', 2, 'Krapfentaxi', NULL, $2::jsonb)
        """,
        current_action_id,
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")),
    )
    form = snapshot["orderForm"]
    assert isinstance(form, dict)
    await connection.execute(
        """
        INSERT INTO order_form_configuration (
            id, action_id, form_key, status, title, introduction,
            submit_label, require_company_name, require_contact_name,
            require_email, require_phone, require_delivery_address,
            require_billing_address, allow_message
        )
        VALUES (
            $1, $2, $3, 'active', $4, $5, $6,
            $7, $8, $9, $10, $11, $12, $13
        )
        """,
        form_id,
        current_action_id,
        form["formKey"],
        form["title"],
        form["introduction"],
        form["submitLabel"],
        form["requireCompanyName"],
        form["requireContactName"],
        form["requireEmail"],
        form["requirePhone"],
        form["requireDeliveryAddress"],
        form["requireBillingAddress"],
        form["allowMessage"],
    )


async def seed_operational_golden(
    connection: asyncpg.Connection[Any],
    dataset: JsonObject,
    documents: list[JsonObject],
) -> None:
    assignment_ids = [item["id"] for item in dataset["assignments"]]
    activity_ids = [item["id"] for item in dataset["activities"]]
    commitment_ids = [item["id"] for item in dataset["commitments"]]
    golden_action_ids = [item["id"] for item in dataset["actions"]]
    invoice_ids = await connection.fetch(
        "SELECT id FROM invoice WHERE action_id = ANY($1::uuid[])",
        golden_action_ids,
    )
    scoped_invoice_ids = [row["id"] for row in invoice_ids]
    document_ids = await connection.fetch(
        "SELECT id FROM generated_document WHERE invoice_id = ANY($1::uuid[])",
        scoped_invoice_ids,
    )
    scoped_document_ids = [row["id"] for row in document_ids]

    await connection.execute(
        "DELETE FROM payment_record WHERE invoice_id = ANY($1::uuid[])",
        scoped_invoice_ids,
    )
    await connection.execute(
        """
        DELETE FROM outbox_event
        WHERE aggregate_type = 'generated_document'
          AND aggregate_id = ANY($1::uuid[])
        """,
        scoped_document_ids,
    )
    await connection.execute(
        "DELETE FROM generated_document WHERE invoice_id = ANY($1::uuid[])",
        scoped_invoice_ids,
    )
    await connection.execute(
        "DELETE FROM invoice WHERE id = ANY($1::uuid[])",
        scoped_invoice_ids,
    )
    await connection.execute(
        "DELETE FROM acquisition_activity WHERE id = ANY($1::uuid[])",
        activity_ids,
    )
    await connection.execute(
        "DELETE FROM commitment WHERE id = ANY($1::uuid[])",
        commitment_ids,
    )
    await connection.execute(
        "DELETE FROM acquisition_assignment WHERE id = ANY($1::uuid[])",
        assignment_ids,
    )
    await connection.execute(
        "DELETE FROM invoice_profile WHERE action_id = ANY($1::uuid[])",
        golden_action_ids,
    )

    for offer in dataset["offers"]:
        await connection.execute(
            """
            INSERT INTO offering (
                id, action_id, code, name, status, unit,
                allowed_quantity_units, pieces_per_unit,
                unit_price_minor, currency,
                available_from, available_until
            )
            VALUES (
                $1, $2, $3, $4, $5, $6,
                $7::text[], $8, $9, $10, $11, $12
            )
            ON CONFLICT (id) DO UPDATE
            SET code = EXCLUDED.code,
                name = EXCLUDED.name,
                status = EXCLUDED.status,
                unit = EXCLUDED.unit,
                allowed_quantity_units = EXCLUDED.allowed_quantity_units,
                pieces_per_unit = EXCLUDED.pieces_per_unit,
                unit_price_minor = EXCLUDED.unit_price_minor,
                currency = EXCLUDED.currency,
                available_from = EXCLUDED.available_from,
                available_until = EXCLUDED.available_until,
                updated_at = CURRENT_TIMESTAMP
            """,
            offer["id"],
            offer["actionId"],
            offer["code"],
            offer["name"],
            "active" if offer["active"] else "inactive",
            str(offer["unit"]).casefold(),
            [str(value).casefold() for value in offer["allowedQuantityUnits"]],
            offer["piecesPerUnit"],
            offer["unitPriceCents"],
            offer["currency"],
            datetime.fromisoformat(str(offer["availableFrom"])),
            datetime.fromisoformat(str(offer["availableUntil"])),
        )

    assignment_lookup: dict[tuple[str, str, str], str] = {}
    for assignment in dataset["assignments"]:
        party_id = str(assignment["companyId"] or assignment["personId"])
        assignment_lookup[
            (
                str(assignment["actionId"]),
                party_id,
                str(assignment["acquirerId"]),
            )
        ] = str(assignment["id"])
        await connection.execute(
            """
            INSERT INTO acquisition_assignment (
                id,
                action_id,
                twenty_company_id,
                twenty_person_id,
                acquirer_user_id,
                status,
                priority
            )
            VALUES ($1, $2, $3, $4, $5, 'open', 0)
            """,
            assignment["id"],
            assignment["actionId"],
            assignment["companyId"],
            assignment["personId"],
            assignment["acquirerId"],
        )
        await connection.execute(
            """
            INSERT INTO acquisition_assignment_history (
                id,
                assignment_id,
                changed_by_user_id,
                previous_state,
                new_state,
                changed_at
            )
            VALUES ($1, $2, $3, '{}'::jsonb, $4::jsonb, $5)
            """,
            uuid5(
                ASSIGNMENT_HISTORY_NAMESPACE,
                f"golden-assignment:{assignment['id']}:initial",
            ),
            assignment["id"],
            assignment["acquirerId"],
            json.dumps(
                {
                    "status": "open",
                    "priority": 0,
                    "nextAction": None,
                    "dueAt": None,
                    "acquirerUserId": assignment["acquirerId"],
                },
                separators=(",", ":"),
            ),
            GOLDEN_ASSIGNMENT_CHANGED_AT,
        )

    offers = {str(item["id"]): item for item in dataset["offers"]}
    companies = {str(item["id"]): item for item in dataset["companies"]}
    persons = {str(item["id"]): item for item in dataset["persons"]}
    people_by_company: dict[str, list[JsonObject]] = {}
    for person in dataset["persons"]:
        company_id = person.get("companyId")
        if company_id is not None:
            people_by_company.setdefault(str(company_id), []).append(person)
    invoices_by_commitment = {
        str(item["commitmentId"]): item for item in dataset["invoices"]
    }
    source = {
        "ACQUISITION": "acquisition",
        "PUBLIC_FORM": "public_form",
        "ADMIN": "admin",
    }
    commitment_status = {
        "DRAFT": "draft",
        "REVIEW_READY": "review_ready",
        "PUBLIC_RECEIVED": "review_ready",
        "INVOICED": "invoiced",
    }
    commitments_by_id: dict[str, JsonObject] = {}
    for commitment_index, commitment in enumerate(dataset["commitments"]):
        commitments_by_id[str(commitment["id"])] = commitment
        total_minor = sum(
            int(line["quantity"]) * int(offers[str(line["offerId"])]["unitPriceCents"])
            for line in commitment["lines"]
        )
        invoice = invoices_by_commitment.get(str(commitment["id"]))
        company_id = commitment["companyId"]
        person_id = commitment["personId"]
        if company_id is not None:
            company = companies[str(company_id)]
            company_people = people_by_company.get(str(company_id), [])
            buyer_email = str(company_people[0]["email"]) if company_people else None
            customer_snapshot = {
                "partyKind": "company",
                "twentyId": str(company_id),
                "displayName": str(company["name"]),
                "email": buyer_email,
            }
        else:
            person = persons[str(person_id)]
            buyer_email = str(person["email"])
            customer_snapshot = {
                "partyKind": "person",
                "twentyId": str(person_id),
                "displayName": (
                    f"{person['givenName']} {person['familyName']}".strip()
                ),
                "email": buyer_email,
            }
        invoice_address = commitment.get("invoiceAddress")
        if isinstance(invoice_address, dict):
            address = invoice_address
            recipient_snapshot = {
                "recipientName": address["recipient"],
                "streetLine1": address["street"],
                "postalCode": address["postalCode"],
                "city": address["city"],
                "countryCode": address["country"],
                "email": buyer_email,
            }
        elif invoice is not None:
            address = invoice["addressSnapshot"]
            recipient_snapshot = {
                "recipientName": address["recipient"],
                "streetLine1": address["street"],
                "postalCode": address["postalCode"],
                "city": address["city"],
                "countryCode": address["country"],
                "email": buyer_email,
            }
        else:
            recipient_snapshot = None
        delivery = commitment.get("deliveryAddress")
        delivery_snapshot = (
            {
                "recipientName": delivery["recipient"],
                "streetLine1": delivery["street"],
                "postalCode": delivery["postalCode"],
                "city": delivery["city"],
                "countryCode": delivery["country"],
            }
            if isinstance(delivery, dict)
            else None
        )
        public_reference = (
            f"LA-{str(commitment['id']).replace('-', '').upper()}"
            if source[str(commitment["source"])] == "public_form"
            else None
        )
        created_at = GOLDEN_COMMITMENT_CREATED_AT + timedelta(minutes=commitment_index)
        await connection.execute(
            """
            INSERT INTO commitment (
                id,
                action_id,
                twenty_company_id,
                twenty_person_id,
                source,
                status,
                customer_snapshot,
                invoice_recipient_snapshot,
                delivery_recipient_snapshot,
                message_snapshot,
                public_reference,
                currency,
                total_minor,
                created_at,
                updated_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7::json, $8::json,
                $9::json, NULL, $10, 'EUR', $11, $12, $12
            )
            """,
            commitment["id"],
            commitment["actionId"],
            commitment["companyId"],
            commitment["personId"],
            source[str(commitment["source"])],
            commitment_status[str(commitment["status"])],
            json.dumps(customer_snapshot, separators=(",", ":")),
            (
                json.dumps(recipient_snapshot, separators=(",", ":"))
                if recipient_snapshot is not None
                else None
            ),
            (
                json.dumps(delivery_snapshot, separators=(",", ":"))
                if delivery_snapshot is not None
                else None
            ),
            public_reference,
            total_minor,
            created_at,
        )
        for line in commitment["lines"]:
            offer = offers[str(line["offerId"])]
            await connection.execute(
                """
                INSERT INTO commitment_line (
                    id, commitment_id, offering_id, description_snapshot,
                    quantity, unit_snapshot, pieces_per_unit_snapshot,
                    unit_price_minor, line_total_minor
                )
                VALUES (
                    $1, $2, $3, $4, $5, $6, $7, $8, $9
                )
                """,
                uuid5(
                    ASSIGNMENT_HISTORY_NAMESPACE,
                    f"golden-commitment-line:{commitment['id']}:{line['offerId']}",
                ),
                commitment["id"],
                line["offerId"],
                offer["name"],
                line["quantity"],
                str(offer["unit"]).casefold(),
                offer["piecesPerUnit"],
                offer["unitPriceCents"],
                int(line["quantity"]) * int(offer["unitPriceCents"]),
            )

    activity_origin = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)
    for index, activity in enumerate(dataset["activities"]):
        party_id = str(activity["companyId"] or activity.get("personId"))
        actor_id = activity["actorId"]
        assignment_id = (
            assignment_lookup.get(
                (
                    str(activity["actionId"]),
                    party_id,
                    str(actor_id),
                )
            )
            if actor_id is not None
            else None
        )
        await connection.execute(
            """
            INSERT INTO acquisition_activity (
                id,
                action_id,
                assignment_id,
                actor_user_id,
                commitment_id,
                twenty_company_id,
                twenty_person_id,
                occurred_at,
                channel,
                outcome,
                note
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NULL)
            """,
            activity["id"],
            activity["actionId"],
            assignment_id,
            actor_id,
            activity["commitmentId"],
            activity["companyId"],
            activity.get("personId"),
            activity_origin + timedelta(minutes=index),
            (
                "public_form"
                if str(activity["kind"]).startswith("PUBLIC_")
                else "system"
            ),
            str(activity["kind"]).casefold(),
        )

    tax_treatment = {
        "STANDARD_VAT": "standard_vat",
        "SMALL_BUSINESS": "small_business",
        "TAX_EXEMPT": "tax_exempt",
    }
    for profile in dataset["invoiceProfiles"]:
        await connection.execute(
            """
            INSERT INTO invoice_profile (
                id, action_id, legal_name, street_line_1, postal_code, city,
                country_code, tax_identifier, email, tax_treatment,
                tax_rate_basis_points, tax_note, number_prefix, next_number,
                number_width, payment_terms_days, confirmed_at
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                $11, $12, $13, $14, $15, $16, $17
            )
            """,
            profile["id"],
            profile["actionId"],
            profile["legalName"],
            profile["street"],
            profile["postalCode"],
            profile["city"],
            profile["country"],
            profile["taxIdentifier"],
            profile["email"],
            tax_treatment[str(profile["taxTreatment"])],
            profile["taxRateBasisPoints"],
            profile["taxNote"],
            profile["numberPrefix"],
            profile["nextNumber"],
            profile["numberWidth"],
            profile["paymentTermsDays"],
            datetime.fromisoformat(str(profile["confirmedAt"])),
        )

    invoice_status = {
        "OPEN": "issued",
        "PAID": "paid",
        "CANCELLED": "cancelled",
    }
    profiles_by_action = {
        str(item["actionId"]): item for item in dataset["invoiceProfiles"]
    }
    issued_at = datetime(2026, 6, 30, 12, tzinfo=timezone.utc)
    for invoice in dataset["invoices"]:
        commitment = commitments_by_id[str(invoice["commitmentId"])]
        profile = profiles_by_action[str(commitment["actionId"])]
        amount = int(invoice["amountCents"])
        issuer_snapshot = {
            "legalName": profile["legalName"],
            "streetLine1": profile["street"],
            "postalCode": profile["postalCode"],
            "city": profile["city"],
            "countryCode": profile["country"],
            "taxIdentifier": profile["taxIdentifier"],
            "email": profile["email"],
        }
        recipient_source = invoice["addressSnapshot"]
        recipient_snapshot = {
            "recipientName": recipient_source["recipient"],
            "streetLine1": recipient_source["street"],
            "postalCode": recipient_source["postalCode"],
            "city": recipient_source["city"],
            "countryCode": recipient_source["country"],
            "email": None,
        }
        line_snapshot = [
            {
                "description": offers[str(line["offerId"])]["name"],
                "quantity": int(line["quantity"]),
                "unit": str(offers[str(line["offerId"])]["unit"]).casefold(),
                "unitPriceGrossMinor": int(
                    offers[str(line["offerId"])]["unitPriceCents"]
                ),
                "taxRateBasisPoints": 0,
                "netMinor": int(line["quantity"])
                * int(offers[str(line["offerId"])]["unitPriceCents"]),
                "taxMinor": 0,
                "grossMinor": int(line["quantity"])
                * int(offers[str(line["offerId"])]["unitPriceCents"]),
                "currency": invoice["currency"],
            }
            for line in commitment["lines"]
        ]
        await connection.execute(
            """
            INSERT INTO invoice (
                id, action_id, commitment_id, number, status, issued_at,
                service_on, due_on, currency, net_minor, tax_minor,
                gross_minor, issuer_snapshot, recipient_snapshot,
                line_snapshot, tax_treatment, tax_rate_basis_points,
                tax_note, payment_reference, approved_by_user_id,
                document_version
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 0, $10,
                $11::jsonb, $12::json, $13::json, $14, 0, $15, $4, $16, 1
            )
            """,
            invoice["id"],
            commitment["actionId"],
            invoice["commitmentId"],
            invoice["number"],
            invoice_status[str(invoice["status"])],
            issued_at,
            date.fromisoformat(
                str(
                    next(
                        action["endsOn"]
                        for action in dataset["actions"]
                        if action["id"] == commitment["actionId"]
                    )
                )
            ),
            issued_at.date() + timedelta(days=14),
            invoice["currency"],
            amount,
            json.dumps(issuer_snapshot, separators=(",", ":")),
            json.dumps(recipient_snapshot, separators=(",", ":")),
            json.dumps(line_snapshot, separators=(",", ":")),
            tax_treatment[str(profile["taxTreatment"])],
            profile["taxNote"],
            "10000000-0000-4000-8000-000000000002",
        )

    document_by_invoice = {str(item["invoiceId"]): item for item in documents}
    for invoice in dataset["invoices"]:
        commitment = commitments_by_id[str(invoice["commitmentId"])]
        document = document_by_invoice.get(str(invoice["id"]))
        if document is None:
            continue
        await connection.execute(
            """
            INSERT INTO generated_document (
                id,
                action_id,
                commitment_id,
                invoice_id,
                twenty_company_id,
                twenty_person_id,
                document_type,
                media_type,
                filename,
                storage_bucket,
                object_key,
                storage_version_id,
                size_bytes,
                sha256,
                render_version,
                version,
                status,
                available_at,
                updated_at
            )
            VALUES (
                $1, $2, $3, $1, $4, $5,
                'invoice_pdf', 'application/pdf', $6, $7,
                $8, $9, $10, $11, $12, 1, 'available',
                $13, $13
            )
            """,
            invoice["id"],
            commitment["actionId"],
            commitment["id"],
            commitment["companyId"],
            commitment["personId"],
            f"Rechnung-{invoice['number']}.pdf",
            require_env("RUSTFS_BUCKET"),
            document["objectKey"],
            document["storageVersionId"],
            document["size"],
            document["sha256"],
            RENDER_VERSION,
            issued_at,
        )


async def seed_core(
    dataset: JsonObject,
    expected: JsonObject,
    dataset_digest: str,
    documents: list[JsonObject],
) -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"), timeout=10)
    try:
        async with connection.transaction():
            await seed_identity(connection, dataset)
            await seed_operational_golden(connection, dataset, documents)
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
    if arguments.command == "seed-core":
        dataset, expected, dataset_digest = load_fixture(fixture)
        await seed_core(dataset, expected, dataset_digest, [])
        print("golden-seed-core: OK: Identitäten und Aktionen in PostgreSQL gesetzt")
    elif arguments.command == "seed-twenty":
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
    for name in ("seed", "seed-core", "seed-twenty", "snapshot", "mutate"):
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
