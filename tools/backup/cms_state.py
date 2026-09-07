"""Reject a recovery point that could reopen CMS bootstrap."""

from __future__ import annotations

import json
from contextlib import ExitStack
import os
from pathlib import Path
import stat
import tarfile
from uuid import UUID


class CmsStateError(ValueError):
    """Static diagnostic only: bootstrap state contains an operator identity."""


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise CmsStateError("cms_bootstrap_state_invalid")
        result[key] = value
    return result


def verify_bootstrap_archive(path: Path) -> None:
    try:
        seen: set[str] = set()
        state_seen = False
        state: object = None
        with ExitStack() as stack:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            source = stack.enter_context(os.fdopen(descriptor, "rb"))
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise CmsStateError("cms_bootstrap_archive_invalid")
            archive = stack.enter_context(tarfile.open(fileobj=source, mode="r:"))
            for member in archive:
                if len(seen) >= 2 or member.name in seen:
                    raise CmsStateError("cms_bootstrap_archive_invalid")
                seen.add(member.name)
                if member.name in {".", "./"} and member.isdir():
                    continue
                if (
                    member.name not in {"state.json", "./state.json"}
                    or not member.isfile()
                    or member.size > 1024
                    or member.mode != 0o600
                    or state_seen
                ):
                    raise CmsStateError("cms_bootstrap_archive_invalid")
                stream = archive.extractfile(member)
                if stream is None:
                    raise CmsStateError("cms_bootstrap_archive_invalid")
                with stream:
                    state_seen = True
                    state = json.loads(
                        stream.read(1025), object_pairs_hook=unique_object
                    )
        if not isinstance(state, dict) or set(state) != {
            "version",
            "status",
            "actor",
            "expiresAt",
        }:
            raise CmsStateError("cms_bootstrap_state_invalid")
        actor = state["actor"]
        if (
            type(state["version"]) is not int
            or state["version"] != 1
            or state["status"] != "complete"
            or not isinstance(actor, str)
            or str(UUID(actor)) != actor
            or type(state["expiresAt"]) is not int
            or not 0 <= state["expiresAt"] <= 2**53 - 1
        ):
            raise CmsStateError("cms_bootstrap_not_complete")
    except (OSError, ValueError, tarfile.TarError) as error:
        raise CmsStateError("cms_bootstrap_recovery_refused") from error
