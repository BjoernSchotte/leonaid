"""Actual PostgreSQL survey upgrade and constraint assertions."""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

import asyncpg

TABLES = {
    "survey",
    "survey_draft",
    "survey_version",
    "survey_participation",
    "survey_operation",
    "survey_grant",
    "survey_settings",
    "survey_settings_operation",
    "survey_invitation",
    "survey_analysis_snapshot",
    "survey_export_job",
    "survey_deletion",
    "survey_recovery_identity",
}
BASELINE = "0026_invoice_payment_snapshot"
HEAD = "0034_survey_recovery_identity"


async def fingerprints(conn, tables):
    result = {}
    for table in tables:
        quoted = '"' + table.replace('"', '""') + '"'
        content = await conn.fetchval(
            f"SELECT COALESCE(jsonb_agg(to_jsonb(t) ORDER BY to_jsonb(t)::text),'[]'::jsonb)::text FROM public.{quoted} t"
        )
        result[table] = {
            "rows": len(json.loads(content)),
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
        }
    return result


async def constraints(conn):
    owner, first, second, version, participation = [uuid4() for _ in range(5)]
    transaction = conn.transaction()
    await transaction.start()
    checked = []
    try:
        await conn.execute(
            "INSERT INTO user_account(id,email,display_name,status) VALUES($1,$2,'Migration fixture','active')",
            owner,
            f"{owner}@example.invalid",
        )
        for sid in [first, second]:
            await conn.execute(
                "INSERT INTO survey(id,title,owner_user_id) VALUES($1,'Synthetic migrated survey',$2)",
                sid,
                owner,
            )
            await conn.execute(
                "INSERT INTO survey_draft(survey_id,definition) VALUES($1,$2::jsonb)",
                sid,
                '{"pages":[{"name":"page","elements":[{"type":"text","name":"answer"}]}]}',
            )
        await conn.execute(
            "INSERT INTO survey_version(id,survey_id,number,definition,schema_hash,renderer_version,capability_profile) SELECT $1,survey_id,1,definition,'synthetic','3.0.3','initial-v1' FROM survey_draft WHERE survey_id=$2",
            version,
            first,
        )
        await conn.execute(
            "INSERT INTO survey_participation(id,survey_id,version_id,resume_digest,inactivity_timeout_seconds) VALUES($1,$2,$3,$4,1800)",
            participation,
            first,
            version,
            str(uuid4()),
        )

        async def rejected(name, sql, *args):
            try:
                async with conn.transaction():
                    await conn.execute(sql, *args)
                    # Publication's composite FK is intentionally deferred until commit.
                    await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")
            except asyncpg.PostgresError as error:
                assert error.sqlstate in {"23000", "23514", "23503", "23505"}, (
                    name,
                    error.sqlstate,
                )
                checked.append(name)
                return
            raise AssertionError(f"Missing database invariant: {name}")

        await rejected(
            "immutable publication",
            "UPDATE survey_version SET definition='{}'::jsonb WHERE id=$1",
            version,
        )
        await rejected(
            "version belongs to participation survey",
            "UPDATE survey_participation SET survey_id=$1 WHERE id=$2",
            second,
            participation,
        )
        await rejected(
            "published version belongs to survey",
            "UPDATE survey SET published_version_id=$1 WHERE id=$2",
            version,
            second,
        )
        await rejected(
            "invitation participation belongs to same survey",
            "INSERT INTO survey_invitation(id,survey_id,recipient_email,token_digest,participation_id,redeemed_at,expires_at) VALUES($1,$2,'synthetic@example.com',$3,$4,now(),now()+interval '1 day')",
            uuid4(),
            second,
            str(uuid4()),
            participation,
        )
        await rejected(
            "invitation redemption timestamp matches association",
            "INSERT INTO survey_invitation(id,survey_id,recipient_email,token_digest,participation_id,expires_at) VALUES($1,$2,'synthetic@example.com',$3,$4,now()+interval '1 day')",
            uuid4(),
            first,
            str(uuid4()),
            participation,
        )
        await rejected(
            "positive participation timeout",
            "UPDATE survey_participation SET inactivity_timeout_seconds=0 WHERE id=$1",
            participation,
        )
        snapshot_id = uuid4()
        payload = json.dumps(
            {
                "id": str(snapshot_id),
                "surveyId": str(first),
                "filter": {"versionId": str(version)},
            }
        )
        await conn.execute(
            "INSERT INTO survey_analysis_snapshot(id,survey_id,version_id,payload,private_responses,created_at) VALUES($1,$2,$3,$4::jsonb,'[]',now())",
            snapshot_id,
            first,
            version,
            payload,
        )
        await rejected(
            "immutable analysis snapshot",
            "UPDATE survey_analysis_snapshot SET payload='{}' WHERE id=$1",
            snapshot_id,
        )
        invalid_id = uuid4()
        await rejected(
            "analysis version belongs to same survey",
            "INSERT INTO survey_analysis_snapshot(id,survey_id,version_id,payload,private_responses,created_at) VALUES($1,$2,$3,$4::jsonb,'[]',now())",
            invalid_id,
            second,
            version,
            json.dumps(
                {
                    "id": str(invalid_id),
                    "surveyId": str(second),
                    "filter": {"versionId": str(version)},
                }
            ),
        )
        await rejected(
            "analysis metadata requires version identity",
            "INSERT INTO survey_analysis_snapshot(id,survey_id,version_id,payload,private_responses,created_at) VALUES($1,$2,$3,$4::jsonb,'[]',now())",
            uuid4(),
            first,
            version,
            "{}",
        )
        job_id, event_id = uuid4(), uuid4()
        await conn.execute(
            "INSERT INTO outbox_event(id,aggregate_type,aggregate_id,event_type,idempotency_key,payload) VALUES($1,'survey_export',$2,'survey.export.render.v1',$3,'{}')",
            event_id,
            job_id,
            str(job_id),
        )
        await conn.execute(
            "INSERT INTO survey_export_job(id,survey_id,snapshot_id,requested_by,operation_id,request_hash,title,product,event_id) VALUES($1,$2,$3,$4,'synthetic',$5,'Synthetic export','analysis_xlsx',$6)",
            job_id,
            first,
            snapshot_id,
            owner,
            "0" * 64,
            event_id,
        )
        await rejected(
            "immutable export input",
            "UPDATE survey_export_job SET snapshot_id=$2 WHERE id=$1",
            job_id,
            uuid4(),
        )
        await rejected(
            "available export requires complete object metadata",
            "UPDATE survey_export_job SET status='available' WHERE id=$1",
            job_id,
        )
        await rejected(
            "export reference prevents uncontrolled snapshot deletion",
            "DELETE FROM survey_analysis_snapshot WHERE id=$1",
            snapshot_id,
        )
        await rejected(
            "export reference prevents uncontrolled survey deletion",
            "DELETE FROM survey WHERE id=$1",
            first,
        )
        foreign_job, foreign_event = uuid4(), uuid4()
        await conn.execute(
            "INSERT INTO outbox_event(id,aggregate_type,aggregate_id,event_type,idempotency_key,payload) VALUES($1,'survey_export',$2,'survey.export.render.v1',$3,'{}')",
            foreign_event,
            foreign_job,
            str(foreign_job),
        )
        await rejected(
            "export snapshot belongs to survey",
            "INSERT INTO survey_export_job(id,survey_id,snapshot_id,requested_by,operation_id,request_hash,title,product,event_id) VALUES($1,$2,$3,$4,'synthetic',$5,'Synthetic export','analysis_xlsx',$6)",
            foreign_job,
            second,
            snapshot_id,
            owner,
            "0" * 64,
            foreign_event,
        )
        await rejected(
            "bounded survey timeout",
            "UPDATE survey SET inactivity_timeout_seconds=604801 WHERE id=$1",
            first,
        )
        await rejected(
            "completion timestamp required",
            "UPDATE survey_participation SET status='completed' WHERE id=$1",
            participation,
        )
        await rejected(
            "trash timestamp required",
            "UPDATE survey SET status='deleted' WHERE id=$1",
            first,
        )
        await rejected(
            "known lifecycle state",
            "UPDATE survey SET status='unexpected' WHERE id=$1",
            first,
        )
        await rejected(
            "one version number per survey",
            "INSERT INTO survey_version(id,survey_id,number,definition,schema_hash,renderer_version,capability_profile) SELECT $1,survey_id,number,definition,schema_hash,renderer_version,capability_profile FROM survey_version WHERE id=$2",
            uuid4(),
            version,
        )
        await rejected(
            "known grant capability",
            "INSERT INTO survey_grant(survey_id,user_id,capability) VALUES($1,$2,'unexpected')",
            first,
            owner,
        )
        await rejected(
            "singleton settings", "INSERT INTO survey_settings(singleton) VALUES(false)"
        )
        await conn.execute(
            "UPDATE survey_participation SET last_answer_changed_at=statement_timestamp()-interval '1 hour',answers=$2::jsonb WHERE id=$1",
            participation,
            '{"answer":"Synthetic retained answer"}',
        )
        effective = await conn.fetchrow(
            "SELECT status,effective_status,answers FROM survey_participation_effective WHERE id=$1",
            participation,
        )
        assert (
            effective["status"] == "in_progress"
            and effective["effective_status"] == "partial"
        )
        assert json.loads(effective["answers"]) == {
            "answer": "Synthetic retained answer"
        }
        checked.append("effective partial status preserves answers")
        await rejected(
            "positive retention duration",
            "UPDATE survey_settings SET ended_retention_seconds=0,retention_configured_by=$1",
            owner,
        )
        await rejected(
            "bounded retention duration",
            "UPDATE survey_settings SET trash_retention_seconds=315360001,retention_configured_by=$1",
            owner,
        )
        await rejected(
            "retention requires accountable actor",
            "UPDATE survey_settings SET ended_retention_seconds=3600,retention_configured_by=NULL",
        )
        await rejected(
            "singleton recovery identity",
            "INSERT INTO survey_recovery_identity(singleton) VALUES(false)",
        )
        await rejected(
            "deletion record requires content-free operation digest",
            "INSERT INTO survey_deletion(survey_id,requested_by,operation_hash,expected_revision,event_id) VALUES($1,$2,'raw operation',1,$3)",
            second,
            owner,
            uuid4(),
        )
        await conn.execute(
            "INSERT INTO survey_deletion(survey_id,requested_by,operation_hash,expected_revision,event_id) VALUES($1,$2,$3,1,$4)",
            second,
            owner,
            "0" * 64,
            uuid4(),
        )
        await rejected(
            "erasure intent blocks updates",
            "UPDATE survey SET title='recreated content' WHERE id=$1",
            second,
        )
        await conn.execute("DELETE FROM survey WHERE id=$1", second)
        await rejected(
            "erasure intent blocks identity recreation",
            "INSERT INTO survey(id,title,owner_user_id) VALUES($1,'recreated',$2)",
            second,
            owner,
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM survey_deletion WHERE survey_id=$1", second
            )
            == 1
        )
        checked.append("deletion ledger survives survey removal")

    finally:
        await transaction.rollback()
    return checked


async def main():
    conn = await asyncpg.connect(os.environ["CORE_DATABASE_URL"])
    mode = sys.argv[1]
    try:
        current = await conn.fetchval("SELECT version_num FROM alembic_version")
        tables = {
            r["table_name"]
            for r in await conn.fetch(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'"
            )
        }
        baseline_path = Path("/proof/baseline.json")
        if mode == "baseline":
            assert current == BASELINE and not TABLES & tables
            assert await conn.fetchval("SELECT count(*) FROM invoice") > 0
            assert await conn.fetchval("SELECT count(*) FROM commitment") > 0
            state = await fingerprints(conn, sorted(tables - {"alembic_version"}))
            baseline_path.write_text(
                json.dumps({"revision": current, "tables": state}, indent=2)
            )
            print(
                f"PASS: populated pre-survey baseline captured; {len(state)} table fingerprints"
            )
            return
        assert current == HEAD and TABLES <= tables
        assert (
            await conn.fetchval(
                "SELECT inactivity_timeout_seconds FROM survey_settings WHERE singleton"
            )
            == 1800
        )
        assert (
            await conn.fetchval("SELECT revision FROM survey_settings WHERE singleton")
            == 1
        )
        for table in TABLES - {"survey_settings", "survey_recovery_identity"}:
            assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 0
        if mode == "upgrade":
            baseline = json.loads(baseline_path.read_text())
            actual = await fingerprints(conn, sorted(baseline["tables"]))
            assert actual == baseline["tables"], (
                "Pre-existing data changed during survey migrations"
            )
        assert await conn.fetchval("SELECT count(*) FROM survey_recovery_identity") == 1
        assert await conn.fetchval(
            "SELECT installation_id FROM survey_recovery_identity WHERE singleton"
        )
        assert await conn.fetchval(
            "SELECT ended_retention_seconds IS NULL AND trash_retention_seconds IS NULL AND retention_configured_by IS NULL FROM survey_settings WHERE singleton"
        )
        checked = await constraints(conn)
        if mode == "upgrade":
            assert (
                await fingerprints(conn, sorted(baseline["tables"]))
                == baseline["tables"]
            ), "Constraint proof changed existing data"
        Path(f"/proof/{mode}.json").write_text(
            json.dumps(
                {
                    "mode": mode,
                    "revision": current,
                    "preexistingDataPreserved": mode == "upgrade",
                    "checks": checked,
                },
                indent=2,
            )
        )
        print(
            f"PASS: {mode} at {HEAD}; {len(checked)} actual PostgreSQL invariants; existing data preserved where present"
        )
    finally:
        await conn.close()


asyncio.run(main())
