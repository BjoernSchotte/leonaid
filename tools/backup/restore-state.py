#!/usr/bin/env python3
"""Authenticated restore phase receipts; never include configuration or credentials."""

from datetime import datetime, timezone
import argparse
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_private(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o077
            or info.st_size > 65536
        ):
            raise ValueError("unsafe receipt")
        return json.loads(stream.read(65537))


def atomic(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".restore-receipt-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def docker(*args):
    return subprocess.check_output(
        ["docker", *args], text=True, stderr=subprocess.DEVNULL
    ).strip()


def resources(target):
    ids = docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={target}")
    if not ids:
        raise ValueError("restore services missing")
    containers = json.loads(docker("inspect", *ids.splitlines()))
    allowed = {"core-postgres", "twenty-postgres", "rustfs"}
    if any(
        c["Config"]["Labels"].get("com.docker.compose.service") not in allowed
        for c in containers
    ):
        raise ValueError("application containers already exist")
    volumes = {}
    for name in (
        "core-postgres-data",
        "twenty-postgres-data",
        "rustfs-data",
        "twenty-server-data",
    ):
        volume = json.loads(docker("volume", "inspect", f"{target}_{name}"))[0]
        if volume.get("Labels", {}).get("com.docker.compose.project") != target:
            raise ValueError("volume ownership mismatch")
        volumes[name] = {
            "name": volume["Name"],
            "createdAt": volume["CreatedAt"],
            "driver": volume["Driver"],
        }
    return volumes


def context(args):
    config = json.loads(Path(args.config).read_text())
    secret = config["services"]["api"]["environment"]["LEONAID_SESSION_ENCRYPTION_KEY"]
    if not isinstance(secret, str) or len(secret) < 32:
        raise ValueError("missing authentication key")
    key = hmac.digest(secret.encode(), b"leonaid.restore-receipt.v1", "sha256")
    binding = {
        "source": args.source,
        "target": args.target,
        "repositoryHash": hashlib.sha256(args.repository.encode()).hexdigest(),
        "configHash": hashlib.sha256(canonical(config)).hexdigest(),
    }
    if args.expected_manifest:
        binding["expectedManifestHash"] = hashlib.sha256(
            Path(args.expected_manifest).read_bytes()
        ).hexdigest()
    return key, binding


def cutoff(value):
    if not value:
        return None
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("naive cutoff")
    return result.astimezone(timezone.utc)


def receipt(args):
    key, binding = context(args)
    required = cutoff(os.environ.get("LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH", ""))
    if args.action == "prepare":
        manifest_hash = hashlib.sha256(Path(args.manifest).read_bytes()).hexdigest()
        if binding.get("expectedManifestHash", manifest_hash) != manifest_hash:
            raise ValueError("selected backup mismatch")
        payload = {
            "schema": 1,
            "binding": binding,
            "manifestHash": manifest_hash,
            "volumes": resources(args.target),
            "phase": "restored",
            "requiredThrough": required.isoformat() if required else None,
        }
    else:
        envelope = read_private(args.state)
        if set(envelope) != {"payload", "signature"}:
            raise ValueError("invalid receipt envelope")
        payload = envelope["payload"]
        if not hmac.compare_digest(
            envelope["signature"], hmac.digest(key, canonical(payload), "sha256").hex()
        ):
            raise ValueError("receipt authentication failed")
        if (
            set(payload)
            != {
                "schema",
                "binding",
                "manifestHash",
                "volumes",
                "phase",
                "requiredThrough",
            }
            or payload["schema"] != 1
            or payload["binding"] != binding
        ):
            raise ValueError("restore binding mismatch")
        previous = cutoff(payload["requiredThrough"])
        if previous and (required is None or required < previous):
            raise ValueError("recovery cutoff moved backwards")
        if args.action != "complete":
            if payload["phase"] not in {"restored", "verified"} or payload[
                "volumes"
            ] != resources(args.target):
                raise ValueError("restore phase or volumes changed")
        elif payload["phase"] != "starting":
            raise ValueError("restore phase mismatch")
        if args.action == "check":
            print("restore-state: authenticated quarantined target verified")
            return
        payload["requiredThrough"] = required.isoformat() if required else None
        payload["phase"] = {
            "verified": "verified",
            "starting": "starting",
            "complete": "complete",
        }[args.action]
    atomic(
        args.state,
        {
            "payload": payload,
            "signature": hmac.digest(key, canonical(payload), "sha256").hex(),
        },
    )
    print("restore-state: phase recorded")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    lock = sub.add_parser("locked")
    lock.add_argument("--target", required=True)
    lock.add_argument("command", nargs=argparse.REMAINDER)
    for name in ("prepare", "check", "verified", "starting", "complete"):
        command = sub.add_parser(name)
        for field in ("state", "config", "source", "target", "repository"):
            command.add_argument("--" + field, required=True)
        command.add_argument("--manifest")
        command.add_argument("--expected-manifest", default="")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"leonaid-restore-[a-z0-9][a-z0-9-]{0,39}", args.target):
            raise ValueError("invalid restore target")
        if args.action == "locked":
            path = Path(tempfile.gettempdir()) / (args.target + ".restore.lock")
            fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                command = (
                    args.command[1:] if args.command[:1] == ["--"] else args.command
                )
                return subprocess.call(command, pass_fds=(fd,))
            finally:
                os.close(fd)
        receipt(args)
        return 0
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(
            "restore-state: BLOCKED: invalid receipt, changed target or concurrent restore",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
