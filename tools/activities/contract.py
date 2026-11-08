#!/usr/bin/env python3
"""Real API/PostgreSQL activity and reminder contract for POC-061."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import asyncpg
import httpx

from leonaid.adapters.postgres.acquisition import AsyncpgAcquisitionPolicyRepository
from leonaid.application.activities import (
    ACTIVITY_COMMAND_TYPE,
    activity_request_hash,
)
from leonaid.application.errors import Conflict
from leonaid.domain.acquisition import (
    ActivityCapture,
    ActivityChannel,
    ActivityOutcome,
    AssignmentPartyKind,
)
from leonaid.domain.sessions import (
    SESSION_COOKIE_NAME,
    SESSION_LIFETIME,
    session_token_digest,
)

ACTION_ID = UUID("20000000-0000-4000-8000-000000000001")
MUSTERWERK_ID = UUID("40000000-0000-4000-8000-000000000001")
SONNENSEITE_ID = UUID("40000000-0000-4000-8000-000000000002")
BERND_SONNENSEITE_ASSIGNMENT = UUID("60000000-0000-4000-8000-000000000002")
DOPPELKONTAKT_ID = UUID("40000000-0000-4000-8000-000000000003")
KLARA_ID = UUID("10000000-0000-4000-8000-000000000002")
ANNA_ID = UUID("10000000-0000-4000-8000-000000000004")
BERND_ID = UUID("10000000-0000-4000-8000-000000000005")
CARLA_ID = UUID("10000000-0000-4000-8000-000000000006")
ANNA_MUSTERWERK_ASSIGNMENT = UUID("60000000-0000-4000-8000-000000000001")
ANNA_DOPPELKONTAKT_ASSIGNMENT = UUID("60000000-0000-4000-8000-000000000003")
SESSION_NAMESPACE = UUID("e1b83888-86bb-485a-9d05-5803851e5961")
BERLIN = ZoneInfo("Europe/Berlin")


class ContractFailure(RuntimeError):
    pass


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise ContractFailure(f"Missing environment variable: {name}")
    return value


def token_for(user_id: UUID) -> str:
    return f"poc061-{user_id}-server-session-token-value"


async def seed_sessions(connection: asyncpg.Connection[Any]) -> dict[UUID, str]:
    now = datetime.now(timezone.utc)
    users = (KLARA_ID, ANNA_ID, BERND_ID, CARLA_ID)
    await connection.execute(
        "DELETE FROM user_session WHERE user_id = ANY($1::uuid[])",
        list(users),
    )
    tokens: dict[UUID, str] = {}
    for user_id in users:
        token = token_for(user_id)
        tokens[user_id] = token
        await connection.execute(
            """
            INSERT INTO user_session (
                id,
                user_id,
                token_digest,
                expires_at,
                last_seen_at,
                fresh_login_at,
                created_at,
                updated_at
            )
            VALUES ($1, $2, $3, $4, $5, $5, $5, $5)
            """,
            uuid5(SESSION_NAMESPACE, str(user_id)),
            user_id,
            session_token_digest(token),
            now + SESSION_LIFETIME,
            now,
        )
    return tokens


async def request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    token: str,
    request_id: str,
    body: Mapping[str, object] | None = None,
) -> httpx.Response:
    return await client.request(
        method,
        path,
        headers={
            "Cookie": f"{SESSION_COOKIE_NAME}={token}",
            "X-Request-ID": request_id,
        },
        json=body,
    )


def error_code(response: httpx.Response) -> str:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        raise ContractFailure("Error response has no stable contract")
    return str(error.get("code"))


async def exercise(connection: asyncpg.Connection[Any]) -> None:
    tokens = await seed_sessions(connection)
    board_path = f"/api/v1/actions/{ACTION_ID}/acquisition/activity-board"
    activity_path = f"/api/v1/actions/{ACTION_ID}/acquisition/activities"
    today = datetime.now(BERLIN).date()
    yesterday = today - timedelta(days=1)

    async with httpx.AsyncClient(
        base_url=require_env("API_BASE_URL").rstrip("/"),
        timeout=60,
    ) as api:
        initial = await request(
            api,
            "GET",
            board_path,
            tokens[ANNA_ID],
            "poc061:initial-board",
        )
        initial.raise_for_status()
        initial_body = initial.json()
        initial_names = {item["partyDisplayName"] for item in initial_body["workItems"]}
        if initial_names != {"Musterwerk GmbH", "Doppelkontakt AG"}:
            raise ContractFailure(
                f"Anna's work queue is wrong: {sorted(initial_names)}"
            )

        overdue = await request(
            api,
            "POST",
            activity_path,
            tokens[ANNA_ID],
            "poc061:overdue-musterwerk",
            {
                "partyKind": "company",
                "partyId": str(MUSTERWERK_ID),
                "revision": 1,
                "channel": "phone",
                "outcome": "interested",
                "note": "  Einkauf möchte   das Angebot.\n\nKeine sensiblen Angaben.  ",
                "nextAction": "  Angebot per E-Mail senden ",
                "dueOn": yesterday.isoformat(),
            },
        )
        overdue.raise_for_status()
        overdue_body = overdue.json()
        if (
            overdue_body["assignment"]["revision"] != 2
            or overdue_body["assignment"]["status"] != "contacted"
            or overdue_body["activity"]["note"]
            != "Einkauf möchte das Angebot.\n\nKeine sensiblen Angaben."
            or overdue_body["activity"]["nextAction"] != "Angebot per E-Mail senden"
            or overdue_body["activity"]["assignmentRevision"] != 2
        ):
            raise ContractFailure("Overdue activity was not normalized")

        today_activity = await request(
            api,
            "POST",
            activity_path,
            tokens[ANNA_ID],
            "poc061:today-doppelkontakt",
            {
                "partyKind": "company",
                "partyId": str(DOPPELKONTAKT_ID),
                "revision": 1,
                "channel": "email",
                "outcome": "follow_up",
                "note": "Rückmeldung nach interner Abstimmung angekündigt.",
                "nextAction": "Rückmeldung telefonisch einholen",
                "dueOn": today.isoformat(),
            },
        )
        today_activity.raise_for_status()

        stale = await request(
            api,
            "POST",
            activity_path,
            tokens[ANNA_ID],
            "poc061:stale-revision",
            {
                "partyKind": "company",
                "partyId": str(MUSTERWERK_ID),
                "revision": 1,
                "channel": "phone",
                "outcome": "reached",
                "note": None,
                "nextAction": None,
                "dueOn": None,
            },
        )
        if (
            stale.status_code != 409
            or error_code(stale) != "assignment_revision_conflict"
        ):
            raise ContractFailure("Stale activity revision was accepted")

        incomplete = await request(
            api,
            "POST",
            activity_path,
            tokens[ANNA_ID],
            "poc061:incomplete-reminder",
            {
                "partyKind": "company",
                "partyId": str(MUSTERWERK_ID),
                "revision": 2,
                "channel": "phone",
                "outcome": "reached",
                "note": None,
                "nextAction": "Nachfassen",
                "dueOn": None,
            },
        )
        if incomplete.status_code != 422:
            raise ContractFailure("Incomplete follow-up was accepted")

        board = await request(
            api,
            "GET",
            board_path,
            tokens[ANNA_ID],
            "poc061:prioritized-board",
        )
        board.raise_for_status()
        board_body = board.json()
        items = board_body["workItems"]
        if [item["partyDisplayName"] for item in items[:2]] != [
            "Musterwerk GmbH",
            "Doppelkontakt AG",
        ] or [item["urgency"] for item in items[:2]] != ["overdue", "today"]:
            raise ContractFailure("Overdue/today follow-ups are sorted wrongly")
        activities = board_body["activities"]
        if (
            len(activities) != 2
            or activities[0]["partyDisplayName"] != "Doppelkontakt AG"
            or activities[1]["partyDisplayName"] != "Musterwerk GmbH"
            or activities[0]["actorDisplayName"] != "Anna Akquise"
        ):
            raise ContractFailure("Append-only activity history is sorted wrongly")

        shared = await request(
            api,
            "GET",
            board_path,
            tokens[BERND_ID],
            "poc061:shared-history",
        )
        shared.raise_for_status()
        shared_activities = shared.json()["activities"]
        if (
            len(shared_activities) != 1
            or shared_activities[0]["partyDisplayName"] != "Doppelkontakt AG"
            or shared_activities[0]["actorDisplayName"] != "Anna Akquise"
        ):
            raise ContractFailure("Co-assignee does not see the shared history")

        concealed = await request(
            api,
            "GET",
            board_path,
            tokens[CARLA_ID],
            "poc061:foreign-history",
        )
        concealed.raise_for_status()
        if concealed.json()["activities"]:
            raise ContractFailure("Unrelated persona sees Anna's activities")

        admin_forbidden = await request(
            api,
            "GET",
            board_path,
            tokens[KLARA_ID],
            "poc061:admin-not-acquirer",
        )
        if (
            admin_forbidden.status_code != 403
            or error_code(admin_forbidden) != "acquirer_required"
        ):
            raise ContractFailure("Charity admin received the acquirer work queue")

        database_rows = await connection.fetch(
            """
            SELECT
                activity.id,
                activity.assignment_id,
                activity.assignment_revision,
                activity.note,
                activity.next_action_snapshot,
                activity.due_at_snapshot,
                audit.id AS audit_id,
                audit.payload,
                history.id AS history_id
            FROM acquisition_activity AS activity
            JOIN audit_event AS audit
              ON audit.entity_type = 'acquisition_activity'
             AND audit.entity_id = activity.id
             AND audit.event_type = 'acquisition_activity_recorded'
            JOIN acquisition_assignment_history AS history
              ON history.assignment_id = activity.assignment_id
             AND history.changed_at = activity.occurred_at
            WHERE activity.id = ANY($1::uuid[])
            ORDER BY activity.occurred_at
            """,
            [
                UUID(overdue_body["activity"]["id"]),
                UUID(today_activity.json()["activity"]["id"]),
            ],
        )
        if len(database_rows) != 2:
            raise ContractFailure(
                "Activity, AuditEvent and history were not written atomically"
            )
        for row in database_rows:
            payload = (
                json.loads(row["payload"])
                if isinstance(row["payload"], str)
                else row["payload"]
            )
            if (
                int(row["assignment_revision"]) != 2
                or row["audit_id"] is None
                or row["history_id"] is None
                or not isinstance(payload, dict)
                or "note" in payload
                or int(payload.get("noteLength", -1)) < 0
            ):
                raise ContractFailure("Audit contains wrong or sensitive payload data")

        history_counts = await connection.fetch(
            """
            SELECT assignment_id, count(*) AS entries
            FROM acquisition_assignment_history
            WHERE assignment_id = ANY($1::uuid[])
            GROUP BY assignment_id
            ORDER BY assignment_id
            """,
            [ANNA_MUSTERWERK_ASSIGNMENT, ANNA_DOPPELKONTAKT_ASSIGNMENT],
        )
        if len(history_counts) != 2 or any(
            int(row["entries"]) != 2 for row in history_counts
        ):
            raise ContractFailure("Activities overwrite instead of appending history")

        read_back = {item["id"]: item for item in activities}
        if (
            read_back[overdue_body["activity"]["id"]]["note"]
            != "Einkauf möchte das Angebot.\n\nKeine sensiblen Angaben."
            or read_back[overdue_body["activity"]["id"]]["nextAction"]
            != "Angebot per E-Mail senden"
            or read_back[today_activity.json()["activity"]["id"]]["nextAction"]
            != "Rückmeldung telefonisch einholen"
        ):
            raise ContractFailure("Board does not read back note and next action")

        cleared = await request(
            api,
            "POST",
            activity_path,
            tokens[ANNA_ID],
            "poc061:overdue-cleared",
            {
                "partyKind": "company",
                "partyId": str(MUSTERWERK_ID),
                "revision": 2,
                "channel": "in_person",
                "outcome": "reached",
                "note": "Lieferadresse gemeinsam geprüft.",
                "nextAction": "Lieferadresse bestätigen",
                "dueOn": (today + timedelta(days=3)).isoformat(),
            },
        )
        cleared.raise_for_status()
        after = await request(
            api, "GET", board_path, tokens[ANNA_ID], "poc061:overdue-cleared-board"
        )
        after.raise_for_status()
        urgency = {
            item["partyDisplayName"]: (item["urgency"], item["nextAction"])
            for item in after.json()["workItems"]
        }
        newest = after.json()["activities"][0]
        if (
            urgency["Musterwerk GmbH"] != ("upcoming", "Lieferadresse bestätigen")
            or urgency["Doppelkontakt AG"][0] != "today"
            or newest["id"] != cleared.json()["activity"]["id"]
            or newest["note"] != "Lieferadresse gemeinsam geprüft."
        ):
            raise ContractFailure(f"Overdue follow-up did not move to soon: {urgency}")

        print(
            "activity-contract: OK:",
            "append-only history, reminder priority, co-assignment,",
            "visibility limits, revision, history and audit proven atomic",
        )

        await exercise_offline_queue(api, connection, tokens)


async def send_activity(
    client: httpx.AsyncClient,
    token: str,
    request_id: str,
    body: Mapping[str, object],
    key: str | None,
) -> httpx.Response:
    headers = {
        "Cookie": f"{SESSION_COOKIE_NAME}={token}",
        "X-Request-ID": request_id,
    }
    if key is not None:
        headers["Idempotency-Key"] = key
    return await client.post(
        f"/api/v1/actions/{ACTION_ID}/acquisition/activities",
        headers=headers,
        json=body,
    )


async def exercise_offline_queue(
    api: httpx.AsyncClient,
    connection: asyncpg.Connection[Any],
    tokens: dict[UUID, str],
) -> None:
    """Server part of the PWA offline queue (PLAN §11.1, §11.2, §11.4, §11.5).

    Runs on Bernd's own Sonnenseite assignment, apart from Anna's follow-ups.
    """

    token = tokens[BERND_ID]
    run = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")

    def key(name: str) -> str:
        return f"pwa-q:{run}-{name}"

    async def receipts(value: str) -> int:
        return int(
            await connection.fetchval(
                "SELECT count(*) FROM command_receipt WHERE idempotency_key = $1",
                value,
            )
        )

    async def assignment() -> asyncpg.Record:
        row = await connection.fetchrow(
            """
            SELECT revision, status, next_action, due_at,
                (SELECT count(*) FROM acquisition_assignment_history
                 WHERE assignment_id = $1) AS history,
                (SELECT count(*) FROM acquisition_activity
                 WHERE assignment_id = $1) AS activities
            FROM acquisition_assignment
            WHERE id = $1
            """,
            BERND_SONNENSEITE_ASSIGNMENT,
        )
        if row is None:
            raise ContractFailure("Bernd's Sonnenseite assignment is missing")
        return row

    now = datetime.now(timezone.utc)
    yesterday = (now.astimezone(BERLIN) - timedelta(days=1)).date()
    # 00:30 in Berlin: the UTC day before; the club day is "yesterday".
    captured = datetime(
        yesterday.year, yesterday.month, yesterday.day, 0, 30, tzinfo=BERLIN
    )
    due_on = now.astimezone(BERLIN).date() + timedelta(days=3)
    start = await assignment()
    revision = int(start["revision"])

    def body(**changes: object) -> dict[str, object]:
        values: dict[str, object] = {
            "partyKind": "company",
            "partyId": str(SONNENSEITE_ID),
            "revision": revision,
            "channel": "in_person",
            "outcome": "follow_up",
            "note": "Am Messestand getroffen, offline erfasst.",
            "nextAction": "Angebot schicken",
            "dueOn": due_on.isoformat(),
            "capturedAt": captured.isoformat(),
        }
        values.update(changes)
        return values

    for name, request_body, request_key, code in (
        ("bad-key", body(), "short", "activity_idempotency_key_invalid"),
        (
            "too-old",
            body(capturedAt=(now - timedelta(days=14, minutes=5)).isoformat()),
            key("too-old"),
            "captured_at_out_of_range",
        ),
        (
            "ahead",
            body(capturedAt=(now + timedelta(minutes=10)).isoformat()),
            key("ahead"),
            "captured_at_out_of_range",
        ),
        (
            "naive",
            body(capturedAt="2026-11-04T09:12:30"),
            key("naive"),
            "request_invalid",
        ),
    ):
        refused = await send_activity(
            api, token, f"poc061:offline:{name}", request_body, request_key
        )
        if refused.status_code != 422 or error_code(refused) != code:
            raise ContractFailure(f"Offline capture {name} was not refused: {code}")
        if await receipts(request_key):
            raise ContractFailure(f"Refused offline capture {name} left a receipt")

    # A queued contact on the current revision: recorded at capture time.
    queued_body = body()
    queued = await send_activity(
        api, token, "poc061:offline:queued", queued_body, key("queued")
    )
    queued.raise_for_status()
    queued_json = queued.json()
    activity = queued_json["activity"]
    expected_due = datetime.combine(due_on, datetime.min.time(), tzinfo=BERLIN)
    expected_due = expected_due.replace(hour=9)
    if (
        queued.status_code != 201
        or queued_json["assignmentUpdated"] is not True
        or queued_json["replayed"] is not False
        or datetime.fromisoformat(activity["occurredAt"]) != captured
        or queued_json["assignment"]["revision"] != revision + 1
        or queued_json["assignment"]["status"] != "contacted"
        or datetime.fromisoformat(queued_json["assignment"]["dueAt"]) != expected_due
        or activity["nextAction"] != "Angebot schicken"
    ):
        raise ContractFailure(f"Queued contact was not recorded: {queued_json}")
    stored = await connection.fetchrow(
        """
        SELECT activity.occurred_at, activity.created_at,
            (SELECT max(changed_at) FROM acquisition_assignment_history
             WHERE assignment_id = activity.assignment_id) AS history_at
        FROM acquisition_activity AS activity
        WHERE activity.id = $1
        """,
        UUID(activity["id"]),
    )
    if (
        stored is None
        or stored["occurred_at"] != captured
        or stored["occurred_at"].astimezone(BERLIN).date() != yesterday
        or stored["occurred_at"].astimezone(timezone.utc).date()
        != yesterday - timedelta(days=1)
        # Receive time, not device time, for the record and the history.
        or now - stored["created_at"] > timedelta(minutes=5)
        or now - stored["history_at"] > timedelta(minutes=5)
    ):
        raise ContractFailure("capturedAt and receive time were not split")
    after_queued = await assignment()

    # A lost answer: the resend replays and records nothing new, although
    # its revision is stale by now.
    replay = await send_activity(
        api, token, "poc061:offline:replay", queued_body, key("queued")
    )
    replay.raise_for_status()
    if (
        replay.json()["replayed"] is not True
        or replay.json()["activity"]["id"] != activity["id"]
        or replay.json()["assignment"]["revision"] != revision + 1
        or (await assignment())["activities"] != after_queued["activities"]
    ):
        raise ContractFailure("Activity resend was not replayed")
    changed = await send_activity(
        api,
        token,
        "poc061:offline:changed",
        body(note="Andere Notiz."),
        key("queued"),
    )
    if changed.status_code != 409 or error_code(changed) != "idempotency_conflict":
        raise ContractFailure("Same key with other content was accepted")
    # The key is bound to its account: Anna cannot replay Bernd's entry.
    foreign = await send_activity(
        api, tokens[ANNA_ID], "poc061:offline:foreign", queued_body, key("queued")
    )
    if foreign.status_code != 409 or error_code(foreign) != "idempotency_conflict":
        raise ContractFailure("Another account replayed a foreign activity key")

    # Online capture on a stale revision keeps refusing and stores nothing.
    stale = await send_activity(
        api,
        token,
        "poc061:offline:stale-online",
        body(capturedAt=None, nextAction=None, dueOn=None),
        key("stale-online"),
    )
    if (
        stale.status_code != 409
        or error_code(stale) != "assignment_revision_conflict"
        or await receipts(key("stale-online"))
    ):
        raise ContractFailure("Stale online capture was accepted or kept a key")

    # D1: a queued contact on a moved assignment is recorded; the follow-up
    # and status stay as the assignment has them now.
    moved_body = body(
        outcome="declined",
        nextAction="Nachfassen",
        dueOn=(due_on + timedelta(days=7)).isoformat(),
        capturedAt=(now - timedelta(hours=1)).isoformat(),
        note="Zweiter Kontakt am Stand.",
    )
    moved = await send_activity(
        api, token, "poc061:offline:moved", moved_body, key("moved")
    )
    moved.raise_for_status()
    moved_json = moved.json()
    after_moved = await assignment()
    if (
        moved.status_code != 201
        or moved_json["assignmentUpdated"] is not False
        or moved_json["assignment"]["revision"] != revision + 1
        or moved_json["assignment"]["status"] != "contacted"
        or moved_json["assignment"]["nextAction"] != "Angebot schicken"
        or moved_json["activity"]["nextAction"] is not None
        or moved_json["activity"]["dueAt"] is not None
        or moved_json["activity"]["assignmentRevision"] != revision + 1
        or moved_json["activity"]["outcome"] != "declined"
        or int(after_moved["revision"]) != revision + 1
        or after_moved["status"] != after_queued["status"]
        or after_moved["next_action"] != after_queued["next_action"]
        or after_moved["due_at"] != after_queued["due_at"]
        or after_moved["history"] != after_queued["history"]
        or after_moved["activities"] != after_queued["activities"] + 1
    ):
        raise ContractFailure(f"Moved assignment lost or applied: {moved_json}")
    moved_audit = await connection.fetchval(
        "SELECT payload FROM audit_event WHERE entity_id = $1 "
        "AND event_type = 'acquisition_activity_recorded'",
        UUID(moved_json["activity"]["id"]),
    )
    moved_payload = (
        json.loads(moved_audit) if isinstance(moved_audit, str) else moved_audit
    )
    if (
        not isinstance(moved_payload, dict)
        or moved_payload.get("assignmentUpdated") is not False
        # The follow-up was not applied, so the audit reports none (M6).
        or moved_payload.get("hasReminder") is not False
        or moved_payload.get("followUpRejected") is not True
        or not str(moved_payload.get("capturedAt", "")).endswith("+00:00")
        or "note" in moved_payload
    ):
        raise ContractFailure("Moved-assignment audit is wrong")
    moved_replay = await send_activity(
        api, token, "poc061:offline:moved-replay", moved_body, key("moved")
    )
    moved_replay.raise_for_status()
    if (
        moved_replay.json()["replayed"] is not True
        or moved_replay.json()["assignmentUpdated"] is not False
        or moved_replay.json()["activity"]["id"] != moved_json["activity"]["id"]
    ):
        raise ContractFailure("Moved-assignment resend was not replayed")

    # Two tabs or a retry racing the first send: one activity per key.
    race_body = body(
        revision=revision + 1,
        outcome="reached",
        nextAction=None,
        dueOn=None,
        capturedAt=(now - timedelta(minutes=10)).isoformat(),
        note="Rückruf erhalten.",
    )
    raced = await asyncio.gather(
        *(
            send_activity(
                api, token, f"poc061:offline:race-{index}", race_body, key("race")
            )
            for index in range(5)
        )
    )
    if [response.status_code for response in raced] != [201] * 5:
        raise ContractFailure(
            f"Concurrent sends failed: {[response.text for response in raced]}"
        )
    if (
        len({response.json()["activity"]["id"] for response in raced}) != 1
        or sum(response.json()["replayed"] is False for response in raced) != 1
        or (await assignment())["activities"] != after_moved["activities"] + 1
        or int((await assignment())["revision"]) != revision + 2
    ):
        raise ContractFailure("Concurrent sends of one key recorded twice")

    # I1: a replay after a later change returns the revision that send
    # produced, never the current one; the queue advances its base only from
    # activity.assignmentRevision and only when assignmentUpdated is true.
    late_replay = await send_activity(
        api, token, "poc061:offline:replay-after-change", queued_body, key("queued")
    )
    late_replay.raise_for_status()
    late_json = late_replay.json()
    if (
        late_json["replayed"] is not True
        or late_json["assignmentUpdated"] is not True
        or late_json["activity"]["assignmentRevision"] != revision + 1
        or late_json["assignment"]["revision"] != revision + 2
    ):
        raise ContractFailure(f"Replay returned the current revision: {late_json}")

    # Two queued contacts with different keys on one revision (two devices):
    # both are recorded, exactly one applies its follow-up (D1 under race).
    devices = await asyncio.gather(
        *(
            send_activity(
                api,
                token,
                f"poc061:offline:device-{index}",
                body(
                    revision=revision + 2,
                    capturedAt=(now - timedelta(minutes=20 + index)).isoformat(),
                    note=f"Kontakt von Gerät {index}.",
                ),
                key(f"device-{index}"),
            )
            for index in range(4)
        )
    )
    if [response.status_code for response in devices] != [201] * 4:
        raise ContractFailure(
            f"Racing devices failed: {[response.text for response in devices]}"
        )
    applied = [r.json() for r in devices if r.json()["assignmentUpdated"]]
    after_devices = await assignment()
    if (
        len(applied) != 1
        or applied[0]["activity"]["assignmentRevision"] != revision + 3
        or int(after_devices["revision"]) != revision + 3
        or after_devices["activities"] != after_moved["activities"] + 5
        or any(
            r.json()["activity"]["assignmentRevision"] != revision + 3 for r in devices
        )
    ):
        raise ContractFailure("Racing devices lost a contact or applied twice")

    # M2: a stored capture replays even after its 14-day window closed. The
    # receipt is planted for a 20-day-old capture of the queued activity.
    old_body = body(capturedAt=(now - timedelta(days=20)).isoformat())
    await connection.execute(
        """
        INSERT INTO command_receipt (
            idempotency_key, command_type, request_hash, result, completed_at
        )
        VALUES ($1, $2, $3, $4::jsonb, CURRENT_TIMESTAMP)
        """,
        key("late"),
        ACTIVITY_COMMAND_TYPE,
        activity_request_hash(
            action_id=ACTION_ID,
            actor_user_id=BERND_ID,
            party_kind=AssignmentPartyKind.COMPANY,
            party_id=SONNENSEITE_ID,
            expected_revision=revision,
            channel=ActivityChannel.IN_PERSON,
            outcome=ActivityOutcome.FOLLOW_UP,
            note=str(old_body["note"]),
            next_action=str(old_body["nextAction"]),
            due_on=due_on,
            captured_at=datetime.fromisoformat(str(old_body["capturedAt"])),
        ),
        json.dumps(
            {
                "activityId": activity["id"],
                "assignmentUpdated": True,
                "assignmentRevision": revision + 1,
            }
        ),
    )
    late = await send_activity(
        api, token, "poc061:offline:late-replay", old_body, key("late")
    )
    if late.status_code != 201 or late.json()["replayed"] is not True:
        raise ContractFailure(f"Late resend was not replayed: {late.text}")

    await exercise_repository_races(connection)

    # Ruling 2: after a handover the replay is concealed (404).
    status_before = after_devices["status"]
    await connection.execute(
        "UPDATE acquisition_assignment SET status = 'handed_over' WHERE id = $1",
        BERND_SONNENSEITE_ASSIGNMENT,
    )
    try:
        handed = await send_activity(
            api, token, "poc061:offline:handed-replay", moved_body, key("moved")
        )
        if handed.status_code != 404 or error_code(handed) != "resource_not_found":
            raise ContractFailure(f"Replay after handover leaked: {handed.text}")
    finally:
        await connection.execute(
            "UPDATE acquisition_assignment SET status = $2 WHERE id = $1",
            BERND_SONNENSEITE_ASSIGNMENT,
            status_before,
        )

    print(
        "activity-contract: OK: offline queue: idempotent replay, key bound to",
        "content and account, capturedAt bounds and split from receive time,",
        "contact kept on a moved assignment, one row per concurrent key",
    )


async def exercise_repository_races(connection: asyncpg.Connection[Any]) -> None:
    """Changes between the service's read and the write (M1, ruling 2).

    Over HTTP the window between the read and the locked write cannot be
    hit on purpose, so the repository is called with an assignment read
    before a concurrent change.
    """

    pool = await asyncpg.create_pool(
        require_env("CORE_DATABASE_URL"), min_size=1, max_size=2
    )
    try:
        repository = AsyncpgAcquisitionPolicyRepository(pool)

        async def read() -> Any:
            current = await repository.active_assignment_for_actor(
                action_id=ACTION_ID,
                actor_user_id=BERND_ID,
                party_kind=AssignmentPartyKind.COMPANY,
                party_id=SONNENSEITE_ID,
                evaluated_at=datetime.now(timezone.utc),
            )
            if current is None:
                raise ContractFailure("Bernd's assignment is not active")
            return current

        capture = ActivityCapture.create(
            channel=ActivityChannel.IN_PERSON,
            outcome=ActivityOutcome.DECLINED,
            note="Repository-Nachweis.",
            next_action=None,
            due_at=None,
        )

        async def record(previous: Any, *, expected: int, keep: bool) -> Any:
            received_at = datetime.now(timezone.utc)
            return await repository.record_activity(
                previous,
                previous.record_activity(capture, occurred_at=received_at),
                capture,
                expected_revision=expected,
                actor_user_id=BERND_ID,
                request_id="poc061:offline:repository",
                occurred_at=received_at - timedelta(minutes=1),
                received_at=received_at,
                keep_contact_on_moved_assignment=keep,
            )

        # M1: read at N, the client sends N+1 and a concurrent change moves
        # the row to N+1. The state read at N must not overwrite it.
        stale = await read()
        await connection.execute(
            """
            UPDATE acquisition_assignment
            SET priority = 3, revision = revision + 1
            WHERE id = $1
            """,
            BERND_SONNENSEITE_ASSIGNMENT,
        )
        try:
            await record(stale, expected=stale.revision + 1, keep=False)
        except Conflict as error:
            if error.code != "assignment_revision_conflict":
                raise
        else:
            raise ContractFailure("A newer base revision overwrote a change")
        kept = await record(stale, expected=stale.revision + 1, keep=True)
        moved = await read()
        if (
            kept is None
            or kept.assignment_updated
            or moved.revision != stale.revision + 1
            or moved.state.priority != 3
            or moved.state.status is not stale.state.status
        ):
            raise ContractFailure("A kept contact changed a moved assignment")

        # Ruling 2 for the write: handed over between read and write → None
        # (404), on the read revision and on a moved one.
        before = await read()
        await connection.execute(
            "UPDATE acquisition_assignment SET status = 'handed_over' WHERE id = $1",
            BERND_SONNENSEITE_ASSIGNMENT,
        )
        try:
            for expected in (before.revision, before.revision - 1):
                if await record(before, expected=expected, keep=True) is not None:
                    raise ContractFailure("A handed-over assignment got a contact")
        finally:
            await connection.execute(
                "UPDATE acquisition_assignment SET status = $2 WHERE id = $1",
                BERND_SONNENSEITE_ASSIGNMENT,
                before.state.status.value,
            )
    finally:
        await pool.close()


async def main() -> None:
    connection = await asyncpg.connect(require_env("CORE_DATABASE_URL"))
    try:
        await exercise(connection)
    finally:
        await connection.close()


if __name__ == "__main__":
    asyncio.run(main())
