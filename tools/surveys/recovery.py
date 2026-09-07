"""Offline export/reapply operator primitive. All application writers must be stopped."""

import argparse
import asyncio
import os
from datetime import datetime
from pathlib import Path
import sys
import tempfile

from leonaid.adapters.postgres.pool import create_pool
from leonaid.adapters.postgres.survey_recovery import (
    export_checkpoint,
    reapply_checkpoint,
)
from leonaid.adapters.storage.s3 import S3ObjectStorage
from leonaid.application.surveys.recovery import MAX_DOCUMENT_BYTES, seal, verify


async def execute(args):
    pool = await create_pool(os.environ["CORE_DATABASE_URL"])
    try:
        secret = os.environ["LEONAID_SESSION_ENCRYPTION_KEY"]
        if args.command == "export":
            checkpoint = await export_checkpoint(pool)
            document = seal(checkpoint, secret)
            # Never leave a partly written checkpoint at the operator's path.
            fd, temporary = tempfile.mkstemp(prefix=".erasure-", dir=args.output.parent)
            try:
                with os.fdopen(fd, "wb") as output:
                    output.write(document)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temporary, args.output)
                directory = os.open(args.output.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                Path(temporary).unlink(missing_ok=True)
            print(
                f"survey-recovery: exported {len(checkpoint.records)} content-free records"
            )
        else:
            async with pool.acquire() as conn:
                identity = await conn.fetchval(
                    "SELECT installation_id FROM survey_recovery_identity WHERE singleton"
                )
            with args.checkpoint.open("rb") as input_file:
                document = input_file.read(MAX_DOCUMENT_BYTES + 1)
            checkpoint = verify(
                document,
                secret,
                installation_id=identity,
                required_through=args.required_through,
            )
            storage = S3ObjectStorage(
                endpoint_url=os.environ["OBJECT_STORAGE_ENDPOINT_URL"],
                access_key=os.environ["OBJECT_STORAGE_ACCESS_KEY"],
                secret_key=os.environ["OBJECT_STORAGE_SECRET_KEY"],
                bucket=os.environ["OBJECT_STORAGE_BUCKET"],
                region=os.environ.get("OBJECT_STORAGE_REGION", "us-east-1"),
                path_style=os.environ.get("OBJECT_STORAGE_PATH_STYLE", "true").lower()
                == "true",
            )
            count = await reapply_checkpoint(pool, storage, checkpoint)
            print(f"survey-recovery: reapplied {count} erasures; offline gate passed")
    finally:
        await pool.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--output", type=Path, required=True)
    restore = commands.add_parser("reapply")
    restore.add_argument("--checkpoint", type=Path, required=True)
    restore.add_argument(
        "--required-through", type=datetime.fromisoformat, required=True
    )
    args = parser.parse_args()
    try:
        asyncio.run(execute(args))
    except Exception:
        # A bad file, DB or provider exception must not expose checkpoint contents,
        # credentials, URLs or connection diagnostics in operator/CI logs.
        print(
            "survey-recovery: BLOCKED: checkpoint or erasure verification failed; keep application services stopped",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
