#!/usr/bin/env python3
"""Real FastAPI/PostgreSQL contract for public aliases and archive routes."""

from __future__ import annotations

import asyncio
import hashlib
import html
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid5

import asyncpg
import httpx

from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
CURRENT_ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
ARCHIVED_ACTION_ID = UUID("20000000-0000-4000-8000-000000000002")
DRAFT_ACTION_ID = UUID("20000000-0000-4000-8000-000000000003")
SESSION_NAMESPACE = UUID("5f13740b-a3b0-49df-8e32-f14ae8ccc070")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Umgebungsvariable fehlt: {name}")
    return value


def request_headers(label: str) -> dict[str, str]:
    digest = hashlib.sha256(label.encode()).hexdigest()[:24]
    return {"X-Request-ID": f"poc070:{digest}", "Accept": "application/json"}


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Fehlerantwort besitzt keinen stabilen Vertrag")
    return str(error.get("code"))


async def seed_session(connection: asyncpg.Connection[Any]) -> str:
    now = datetime.now(timezone.utc)
    token = f"poc070-{KLARA_ID}-real-server-session-token"
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = $1",
        KLARA_ID,
    )
    await connection.execute(
        """
        INSERT INTO user_session (
            id, user_id, token_digest, expires_at, last_seen_at,
            fresh_login_at, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
        """,
        uuid5(SESSION_NAMESPACE, str(KLARA_ID)),
        KLARA_ID,
        session_token_digest(token),
        now + SESSION_LIFETIME,
        now,
    )
    return token


def follow_up_payload() -> dict[str, Any]:
    return {
        "templateKey": "krapfentaxi",
        "templateVersion": 1,
        "carrierName": "Lions Club LeonAid Golden",
        "name": "Krapfentaxi 2027",
        "purpose": "Krapfen bestellen und lokale Lernangebote unterstützen.",
        "startsOn": "2027-09-01",
        "endsOn": "2027-11-15",
        "archiveSlug": "krapfentaxi-2027",
        "beneficiaries": [
            {
                "organizationName": "Zukunftswerk Beispielstadt",
                "publicDescription": "Ermöglicht Kindern zusätzliche Lernangebote.",
            }
        ],
        "goal": {
            "goalValue": "1200",
            "actualValue": "0",
            "unit": "Boxen",
            "currency": None,
        },
    }


async def public_alias(
    client: httpx.AsyncClient,
) -> dict[str, Any]:
    response = await client.get(
        "/api/v1/public/actions/alias/krapfentaxi",
        headers=request_headers("alias-read"),
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ContractFailure("Alias-Antwort ist kein Objekt")
    return payload


async def assert_astro_matches(
    client: httpx.AsyncClient,
    path: str,
    direct: dict[str, Any],
) -> None:
    response = await client.get(path, follow_redirects=False)
    if response.status_code != 200:
        raise ContractFailure(
            f"Astro-Route {path} antwortet mit HTTP {response.status_code}"
        )
    expected_state = str(direct["availability"])
    if response.headers.get("X-LeonAid-Public-State") != expected_state:
        raise ContractFailure(
            f"Astro-Route {path} und Core entscheiden unterschiedlich"
        )
    source = response.text
    if "<script" in source.casefold():
        raise ContractFailure(
            f"Astro-Route {path} liefert unnötiges Client-JavaScript aus"
        )
    action = direct.get("action")
    if isinstance(action, dict):
        name = html.escape(str(action["name"]))
        if name not in source:
            raise ContractFailure(
                f"Astro-Route {path} zeigt nicht die vom Core gelieferte Aktion"
            )
        for offering in action.get("offerings", []):
            if html.escape(str(offering["name"])) not in source:
                raise ContractFailure(
                    f"Astro-Route {path} verliert ein öffentliches Angebot"
                )
    elif "Krapfentaxi" in source:
        raise ContractFailure(
            f"Astro-Route {path} gibt bei inaktiver Aktion alte Daten preis"
        )
    canonical_path = str(direct["canonicalPath"])
    canonical_url = response.url.join(canonical_path)
    if f'rel="canonical" href="{canonical_url}"' not in source:
        raise ContractFailure(
            f"Astro-Route {path} besitzt keine passende Canonical URL"
        )


async def exercise(
    connection: asyncpg.Connection[Any],
    token: str,
) -> None:
    now = datetime.now(timezone.utc)
    await connection.execute(
        """
        UPDATE charity_action
        SET publication_starts_at = $2,
            publication_ends_at = $3
        WHERE id = $1
        """,
        CURRENT_ACTION_ID,
        now - timedelta(days=1),
        now + timedelta(days=1),
    )
    await connection.execute(
        """
        INSERT INTO public_action_alias (alias, action_id)
        VALUES ('winterpause', $1)
        """,
        DRAFT_ACTION_ID,
    )

    cookies = {SESSION_COOKIE_NAME: token}
    async with (
        httpx.AsyncClient(
            base_url=require_env("API_BASE_URL").rstrip("/"),
            timeout=30,
        ) as client,
        httpx.AsyncClient(
            base_url=require_env("PUBLIC_BASE_URL").rstrip("/"),
            timeout=30,
        ) as public_client,
    ):
        before = await public_alias(client)
        if (
            before.get("availability") != "published"
            or before.get("submissionsAllowed") is not True
            or before.get("canonicalPath") != "/archive/krapfentaxi-2026"
            or before.get("action", {}).get("id") != str(CURRENT_ACTION_ID)
        ):
            raise ContractFailure("Aktiver Alias löst nicht exakt auf 2026 auf")
        await assert_astro_matches(public_client, "/krapfentaxi", before)

        neutral = await client.get(
            "/api/v1/public/actions/alias/winterpause",
            headers=request_headers("inactive-alias"),
        )
        neutral.raise_for_status()
        if neutral.json() != {
            "routeKind": "alias",
            "routeValue": "winterpause",
            "routePath": "/winterpause",
            "canonicalPath": "/winterpause",
            "availability": "inactive",
            "submissionsAllowed": False,
            "action": None,
        }:
            raise ContractFailure("Inaktiver Alias liefert keine neutrale Sicht")
        await assert_astro_matches(public_client, "/winterpause", neutral.json())

        archive = await client.get(
            "/api/v1/public/actions/archive/krapfentaxi-2025",
            headers=request_headers("archive-read"),
        )
        archive.raise_for_status()
        archive_payload = archive.json()
        if (
            archive_payload.get("availability") != "archive"
            or archive_payload.get("submissionsAllowed") is not False
            or archive_payload.get("canonicalPath") != "/archive/krapfentaxi-2025"
            or archive_payload.get("action", {}).get("id") != str(ARCHIVED_ACTION_ID)
        ):
            raise ContractFailure("Archivroute ist nicht dauerhaft lesbar")
        await assert_astro_matches(
            public_client,
            "/archive/krapfentaxi-2025",
            archive_payload,
        )

        archived_write = await client.put(
            f"/api/v1/actions/{ARCHIVED_ACTION_ID}/goal",
            cookies=cookies,
            headers=request_headers("archive-write"),
            json={
                "revision": 1,
                "goalValue": "999",
                "actualValue": "1",
                "unit": "Boxen",
                "currency": None,
            },
        )
        if (
            archived_write.status_code != 422
            or error_code(archived_write) != "action_archived_immutable"
        ):
            raise ContractFailure("Direkter API-Schreibzugriff auf Archiv war möglich")

        created = await client.post(
            "/api/v1/actions/from-template",
            cookies=cookies,
            headers=request_headers("follow-up-create"),
            json=follow_up_payload(),
        )
        created.raise_for_status()
        follow_up = created.json()["action"]
        follow_up_id = UUID(str(follow_up["id"]))
        revision = int(follow_up["revision"])
        updated = await connection.execute(
            """
            UPDATE offering
            SET status = 'active',
                updated_at = CURRENT_TIMESTAMP
            WHERE action_id = $1
              AND code = 'krapfenbox-24'
            """,
            follow_up_id,
        )
        if updated != "UPDATE 1":
            raise ContractFailure("Golden-Folgejahr besitzt kein aktivierbares Angebot")

        for target_status in ("scheduled", "active"):
            transition = await client.post(
                f"/api/v1/actions/{follow_up_id}/transitions",
                cookies=cookies,
                headers=request_headers(f"follow-up-{target_status}"),
                json={"revision": revision, "targetStatus": target_status},
            )
            transition.raise_for_status()
            revision = int(transition.json()["revision"])

        observations: list[dict[str, Any]] = []

        async def observe_alias() -> None:
            for _index in range(24):
                observations.append(await public_alias(client))
                await asyncio.sleep(0)

        observers = [asyncio.create_task(observe_alias()) for _index in range(3)]
        await asyncio.sleep(0)
        switched = await client.put(
            f"/api/v1/actions/{follow_up_id}/publication",
            cookies=cookies,
            headers=request_headers("follow-up-publish"),
            json={
                "revision": revision,
                "publicationStartsAt": (now - timedelta(hours=1)).isoformat(),
                "publicationEndsAt": (now + timedelta(days=30)).isoformat(),
                "publicAlias": "krapfentaxi",
            },
        )
        switched.raise_for_status()
        await asyncio.gather(*observers)

        after = await public_alias(client)
        observed_ids = {
            item.get("action", {}).get("id")
            for item in [before, *observations, after]
            if isinstance(item.get("action"), dict)
        }
        if (
            after.get("action", {}).get("id") != str(follow_up_id)
            or after.get("canonicalPath") != "/archive/krapfentaxi-2027"
            or after.get("action", {}).get("offerings")
            != [
                {
                    "code": "krapfenbox-24",
                    "name": "Krapfenbox",
                    "unit": "box",
                    "piecesPerUnit": 24,
                    "unitPriceMinor": 3600,
                    "currency": "EUR",
                }
            ]
            or any(item.get("availability") != "published" for item in observations)
            or not observed_ids.issubset({str(CURRENT_ACTION_ID), str(follow_up_id)})
        ):
            raise ContractFailure(
                "Aliaswechsel zeigte einen Zwischenzustand oder falsches Ziel"
            )
        await assert_astro_matches(public_client, "/krapfentaxi", after)
        follow_up_archive = await client.get(
            "/api/v1/public/actions/archive/krapfentaxi-2027",
            headers=request_headers("follow-up-archive"),
        )
        follow_up_archive.raise_for_status()
        await assert_astro_matches(
            public_client,
            "/archive/krapfentaxi-2027",
            follow_up_archive.json(),
        )

        old_archive = await client.get(
            "/api/v1/public/actions/archive/krapfentaxi-2026",
            headers=request_headers("old-archive-after-switch"),
        )
        old_archive.raise_for_status()
        if (
            old_archive.json().get("action", {}).get("id") != str(CURRENT_ACTION_ID)
            or old_archive.json().get("canonicalPath") != "/archive/krapfentaxi-2026"
            or old_archive.json().get("submissionsAllowed") is not False
        ):
            raise ContractFailure("Aliaswechsel veränderte die alte Archivroute")
        await assert_astro_matches(
            public_client,
            "/archive/krapfentaxi-2026",
            old_archive.json(),
        )

        target_rows = await connection.fetch(
            """
            SELECT alias, action_id
            FROM public_action_alias
            WHERE alias = 'krapfentaxi'
            """
        )
        reservations = await connection.fetch(
            """
            SELECT archive_slug, action_id
            FROM action_archive_slug_reservation
            WHERE archive_slug = ANY($1::text[])
            ORDER BY archive_slug
            """,
            [
                "krapfentaxi-2025",
                "krapfentaxi-2026",
                "krapfentaxi-2027",
            ],
        )
        if (
            len(target_rows) != 1
            or target_rows[0]["action_id"] != follow_up_id
            or {(str(row["archive_slug"]), row["action_id"]) for row in reservations}
            != {
                ("krapfentaxi-2025", ARCHIVED_ACTION_ID),
                ("krapfentaxi-2026", CURRENT_ACTION_ID),
                ("krapfentaxi-2027", follow_up_id),
            }
        ):
            raise ContractFailure("Alias oder Archivreservierungen sind inkonsistent")


async def run() -> None:
    connection = await asyncpg.connect(
        require_env("CORE_DATABASE_URL"),
        timeout=10,
    )
    try:
        token = await seed_session(connection)
        await exercise(connection, token)
    finally:
        await connection.close()
    print(
        "public-actions-contract: atomarer Folgejahrwechsel, neutrale Alias-Sicht, "
        "dauerhafte Archive, Astro/Core-Parität, Angebote und Schreibschutz real "
        "bewiesen"
    )


def main() -> int:
    try:
        asyncio.run(run())
    except (ContractFailure, asyncpg.PostgresError, httpx.HTTPError) as error:
        print(f"public-actions-contract: ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
