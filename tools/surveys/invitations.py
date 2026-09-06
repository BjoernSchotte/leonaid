"""Live invitation lifecycle, guarded SMTP, authorization and association checks."""

import asyncio
import json
import os
import re
import sys
from pathlib import Path
from uuid import UUID, uuid4
import asyncpg
import httpx
from leonaid.adapters.mail.secure_payload import SecureMailPayload


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    token = next(
        line.split("=", 1)[1]
        for line in Path("/proof/session.env").read_text().splitlines()
        if line.startswith("SURVEY_ADMIN_SESSION=")
    )
    auth = f"__Host-leonaid_session={token}"
    state_file = Path("/proof/invitations-state.json")
    async with (
        httpx.AsyncClient(base_url="http://api:8000") as client,
        httpx.AsyncClient(base_url="http://mailpit:8025/mail") as mailpit,
    ):

        async def call(method, path, body=None, cookie=None, expected=200):
            client.cookies.clear()
            response = await client.request(
                method, path, json=body, headers={"Cookie": cookie} if cookie else {}
            )
            assert response.status_code == expected, (
                path,
                response.status_code,
                expected,
            )
            return response.json()

        if sys.argv[1] == "prepare":
            state = []
            for kind in ["normal", "revoked", "expired", "closed"]:
                sid = str(uuid4())
                admin = f"/api/v1/surveys/{sid}"
                await call(
                    "POST",
                    admin,
                    {
                        "operationId": "create",
                        "title": f"Synthetic invitation {kind}",
                        "definition": {
                            "pages": [
                                {
                                    "name": "one",
                                    "elements": [{"type": "text", "name": "answer"}],
                                }
                            ]
                        },
                    },
                    auth,
                )
                before = await call("GET", admin, cookie=auth)
                mode = {
                    "operationId": "access",
                    "expectedRevision": before["revision"],
                    "accessMode": "invitation",
                }
                configured = await call("PUT", admin + "/access", mode, auth)
                assert configured == await call("PUT", admin + "/access", mode, auth)
                await call(
                    "POST",
                    admin + "/publish",
                    {"operationId": "publish", "expectedRevision": 1},
                    auth,
                )
                summary = await call("GET", admin, cookie=auth)
                body = {
                    "operationId": "invite",
                    "expectedRevision": summary["revision"],
                    "recipientEmail": f"survey-{kind}@example.com",
                    "recipientName": "Synthetic recipient",
                    "expiresInDays": 30,
                }
                await call("POST", admin + "/invitations", body, expected=401)
                await call(
                    "POST",
                    admin + "/invitations",
                    {**body, "expiresInDays": 0},
                    auth,
                    422,
                )
                await call(
                    "POST",
                    admin + "/invitations",
                    {**body, "recipientEmail": "bad\naddress"},
                    auth,
                    422,
                )
                invitation = await call("POST", admin + "/invitations", body, auth)
                assert invitation == await call(
                    "POST", admin + "/invitations", body, auth
                )
                await call(
                    "POST",
                    admin + "/invitations",
                    {**body, "recipientName": "Changed replay"},
                    auth,
                    409,
                )
                listing = await call("GET", admin + "/invitations", cookie=auth)
                assert listing["total"] == 1 and len(listing["items"]) == 1
                assert not any(
                    key in json.dumps(invitation)
                    for key in ["token", "mail_payload", "participationId"]
                )
                await call("GET", f"/api/v1/public/surveys/{sid}", expected=403)
                await call(
                    "PUT",
                    admin + "/access",
                    {
                        **mode,
                        "operationId": "late-access",
                        "expectedRevision": summary["revision"],
                    },
                    auth,
                    409,
                )
                row = await conn.fetchrow(
                    "SELECT * FROM survey_invitation WHERE id=$1",
                    UUID(invitation["id"]),
                )
                plaintext = SecureMailPayload(
                    os.environ["LEONAID_SESSION_ENCRYPTION_KEY"]
                ).reveal(row["mail_payload"])["text"]
                secret = re.search(r"#invitation=([A-Za-z0-9_-]+)", plaintext).group(1)
                assert secret not in str(dict(row))
                event = await conn.fetchrow(
                    "SELECT * FROM outbox_event WHERE aggregate_id=$1",
                    UUID(invitation["id"]),
                )
                assert (
                    event["payload"] == "{}"
                    and event["event_type"] == "survey.invitation.send.v1"
                )
                state.append(
                    {
                        "survey": sid,
                        "id": invitation["id"],
                        "token": secret,
                        "kind": kind,
                        "revision": summary["revision"],
                    }
                )
                if kind == "revoked":
                    revoked = await call(
                        "POST",
                        admin + f"/invitations/{invitation['id']}/revoke",
                        {
                            "operationId": "revoke",
                            "expectedRevision": summary["revision"],
                        },
                        auth,
                    )
                    assert revoked["status"] == "revoked"
                if kind == "expired":
                    await conn.execute(
                        "UPDATE survey_invitation SET expires_at=now()-interval '1 second' WHERE id=$1",
                        UUID(invitation["id"]),
                    )
                if kind == "closed":
                    await call(
                        "POST",
                        admin + "/transition",
                        {
                            "operationId": "end",
                            "expectedRevision": summary["revision"],
                            "action": "end",
                        },
                        auth,
                    )
            state_file.write_text(json.dumps(state))
            print(
                "PASS: atomic invite creation/replay, secret isolation, invalid inputs, immutable access mode and queued revocation/expiry/closure fixtures"
            )
        elif sys.argv[1] == "recover":
            state = json.loads(state_file.read_text())
            for _ in range(100):
                pending = await conn.fetchval(
                    "SELECT count(*) FROM outbox_event WHERE event_type='survey.invitation.send.v1' AND status!='completed'"
                )
                if pending == 0:
                    break
                await asyncio.sleep(0.25)
            assert pending == 0, "Invitation worker failed to settle"
            messages = (await mailpit.get("/api/v1/messages")).json()["messages"]
            matches = [
                m
                for m in messages
                if any(t["Address"].startswith("survey-") for t in m["To"])
            ]
            assert (
                len(matches) == 1
                and matches[0]["To"][0]["Address"] == "survey-normal@example.com"
            )
            delivered = (
                await mailpit.get(f"/api/v1/message/{matches[0]['ID']}")
            ).json()["Text"]
            normal = state[0]
            assert normal["token"] in delivered
            for entry in state:
                path = f"/api/v1/public/surveys/{entry['survey']}/invitation/redeem"
                if entry["kind"] != "normal":
                    await call(
                        "POST",
                        path,
                        {"token": entry["token"]},
                        expected=409 if entry["kind"] == "closed" else 404,
                    )
                    continue
                row = await conn.fetchrow(
                    "SELECT * FROM survey_invitation WHERE id=$1", UUID(entry["id"])
                )
                assert row["sent_at"] and row["mail_payload"] is None
                p = await call("POST", path, {"token": entry["token"]})
                assert p == await call("POST", path, {"token": entry["token"]})
                public = (
                    f"/api/v1/public/surveys/{entry['survey']}/participations/{p['id']}"
                )
                cookie = f"__Host-survey_{p['id']}={entry['token']}"
                saved = await call(
                    "PUT",
                    public,
                    {
                        "operationId": "save",
                        "expectedRevision": 1,
                        "answers": {"answer": "Attributable synthetic answer"},
                    },
                    cookie,
                )
                await call(
                    "POST",
                    f"/api/v1/surveys/{entry['survey']}/invitations/{entry['id']}/revoke",
                    {"operationId": "revoke", "expectedRevision": entry["revision"]},
                    auth,
                )
                for operation in ["GET", "PUT"]:
                    await call(
                        operation,
                        public,
                        {
                            "operationId": "late",
                            "expectedRevision": saved["revision"],
                            "answers": {},
                        }
                        if operation == "PUT"
                        else None,
                        cookie,
                        404,
                    )
                await call("POST", path, {"token": entry["token"]}, expected=404)
                assert (
                    await conn.fetchval(
                        "SELECT count(*) FROM survey_participation WHERE survey_id=$1",
                        UUID(entry["survey"]),
                    )
                    == 1
                )
                assert await conn.fetchval(
                    "SELECT participation_id FROM survey_invitation WHERE id=$1",
                    UUID(entry["id"]),
                ) == UUID(p["id"])
            print(
                "PASS: real guarded SMTP sends only valid invitation; exact redemption reuses participation; recipient association separate and revoked resume/save/redeem blocked"
            )
            state_file.unlink()
        else:
            state = json.loads(
                Path("/proof/survey-invitation-browser.json").read_text()
            )
            row = await conn.fetchrow(
                "SELECT p.status,p.answers,i.revoked_at,i.recipient_email FROM survey_invitation i JOIN survey_participation p ON p.id=i.participation_id WHERE i.survey_id=$1",
                UUID(state["survey"]),
            )
            assert (
                row["status"] == "completed"
                and row["revoked_at"]
                and row["recipient_email"] == state["email"]
            )
            assert (
                json.loads(row["answers"])["question_first"]
                == "Personal invitation works"
            )
            assert (
                await conn.fetchval(
                    "SELECT count(*) FROM survey_participation WHERE survey_id=$1",
                    UUID(state["survey"]),
                )
                == 1
            )
            print(
                "PASS: actual UI invitation/completion/revocation and one attributable participation verified in PostgreSQL"
            )
    await conn.close()


asyncio.run(main())
