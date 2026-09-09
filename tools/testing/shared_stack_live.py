"""Real stopped-volume reset proof; safe to run alongside another isolated group."""

from pathlib import Path
import subprocess

from shared_stack import SharedStack

ROOT = Path(__file__).resolve().parents[2]


def main():
    stack = SharedStack(ROOT, "survey")
    try:
        stack.prepare()
        original_containers = stack.inventory("containers")
        original_volumes = stack.inventory("volumes")
        stack.call(
            [
                *stack.compose,
                "up",
                "--no-build",
                "--detach",
                "--wait",
                "--wait-timeout",
                "420",
                "api",
                "twenty-worker",
                "mailpit",
            ]
        )
        for service in ("core-postgres", "twenty-postgres"):
            stack.call(
                [
                    *stack.compose,
                    "exec",
                    "-T",
                    service,
                    "sh",
                    "-eu",
                    "-c",
                    'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "CREATE TABLE ci_reset_probe (id integer); INSERT INTO ci_reset_probe VALUES (42);"',
                ]
            )
        stack.call(
            [
                *stack.compose,
                "exec",
                "-T",
                "twenty-redis",
                "redis-cli",
                "SET",
                "ci-reset-probe",
                "dirty",
            ]
        )
        source = """import boto3, os, smtplib
s3=boto3.client("s3", endpoint_url=os.environ["RUSTFS_ENDPOINT_URL"], aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"], aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"])
s3.create_bucket(Bucket="ci-reset-probe")
s3.put_bucket_versioning(Bucket="ci-reset-probe", VersioningConfiguration={"Status":"Enabled"})
for body in (b"first",b"second"): s3.put_object(Bucket="ci-reset-probe", Key="probe", Body=body)
s3.delete_object(Bucket="ci-reset-probe", Key="probe")
assert len(s3.list_object_versions(Bucket="ci-reset-probe")["Versions"]) == 2
with smtplib.SMTP("mailpit",1025) as smtp: smtp.sendmail("probe@example.invalid", "test@example.invalid", "Subject: reset probe\\r\\n\\r\\nsynthetic")
"""
        stack.call(
            [
                *stack.compose,
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "python",
                "api",
                "-c",
                source,
            ]
        )
        # The same cross-process lease used by a real leaf must block the parent.
        lease = stack.directory / "in-use"
        subprocess.run(["mkdir", str(lease)], check=True)
        try:
            try:
                stack.prepare()
            except FileExistsError:
                pass
            else:
                raise AssertionError("Reset was allowed while a leaf held its lease")
        finally:
            lease.rmdir()
        stack.prepare()
        assert stack.inventory("containers") == original_containers
        assert stack.inventory("volumes") == original_volumes
        stack.call(
            [
                *stack.compose,
                "up",
                "--no-build",
                "--detach",
                "--wait",
                "--wait-timeout",
                "420",
                "api",
                "twenty-worker",
                "mailpit",
            ]
        )
        for service in ("core-postgres", "twenty-postgres"):
            value = stack.call(
                [
                    *stack.compose,
                    "exec",
                    "-T",
                    service,
                    "sh",
                    "-eu",
                    "-c",
                    'psql -At -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT to_regclass(\'ci_reset_probe\') IS NULL"',
                ],
                capture=True,
            )
            assert value.strip() == "t", service
        assert (
            stack.call(
                [
                    *stack.compose,
                    "exec",
                    "-T",
                    "twenty-redis",
                    "redis-cli",
                    "EXISTS",
                    "ci-reset-probe",
                ],
                capture=True,
            ).strip()
            == "0"
        )
        verify = """import boto3,json,os,urllib.request
s3=boto3.client("s3", endpoint_url=os.environ["RUSTFS_ENDPOINT_URL"], aws_access_key_id=os.environ["RUSTFS_ACCESS_KEY"], aws_secret_access_key=os.environ["RUSTFS_SECRET_KEY"])
assert "ci-reset-probe" not in [b["Name"] for b in s3.list_buckets()["Buckets"]]
with urllib.request.urlopen("http://mailpit:8025/mail/api/v1/messages") as r: assert json.load(r)["total"] == 0
"""
        stack.call(
            [
                *stack.compose,
                "run",
                "--rm",
                "--no-deps",
                "--entrypoint",
                "python",
                "api",
                "-c",
                verify,
            ]
        )
        print(
            "PASS: unchanged containers/volumes; both databases, Redis, object versions/delete markers and mail reset; concurrent lease refused",
            flush=True,
        )
    finally:
        stack.close()


if __name__ == "__main__":
    main()
