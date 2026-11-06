#!/usr/bin/env python3
"""Verify pinned image digests against their registries and re-pin drift.

Upstream rebuilds move a tag such as python:3.13.18-slim-trixie to a new
digest without a new version. The pin stays reproducible as long as the
recorded digest is still in the registry, so pull requests only require that
(``verify``). A pin a change introduces or alters must also be the digest its
tag resolves to right now (``verify --base-env``). Tag drift is reported by
``verify --all-tags`` and fixed by ``repin``, which rewrites every file that
carries an old digest, with infra/locks/external-systems.lock as the source of
truth, and regenerates infra/locks/images.env from it.

Runs on the host or CI runner: resolving needs ``docker buildx imagetools``.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.pins.check import IMAGE, checkout_files  # noqa: E402

LOCK = Path("infra/locks/external-systems.lock")
ENV = Path("infra/locks/images.env")
ENV_HEADER = (
    "# Generated from external-systems.lock; tools/pins/check.py enforces parity."
)
ENV_LINE = re.compile(r"^(?P<key>[A-Z][A-Z0-9_]*_IMAGE)=(?P<image>\S+)$")
# Proofs under specs/ record what was true when they ran; never rewrite them.
HISTORICAL = {"specs"}
ATTEMPTS = 3

# Maps a reference (name:tag or name@digest) to the digest the registry has.
Resolver = Callable[[str], str]


class PinError(Exception):
    """A pin cannot be read, resolved or rewritten."""


class NotFound(PinError):
    """The registry definitively has no manifest for the reference."""


@dataclass(frozen=True)
class Pin:
    key: str
    image: str
    name: str
    tag: str
    digest: str

    @property
    def tagged(self) -> str:
        return f"{self.name}:{self.tag}"

    @property
    def by_digest(self) -> str:
        return f"{self.name}@{self.digest}"


@dataclass(frozen=True)
class Change:
    system: str
    tagged: str
    old: str
    new: str


def parse_pin(key: str, image: str) -> Pin:
    match = IMAGE.fullmatch(image)
    if not match:
        raise PinError(f"{key}: not a name:tag@sha256 reference: {image}")
    return Pin(key, image, match["name"], match["tag"], match["digest"])


def env_key(system_id: str) -> str:
    return f"{system_id.upper().replace('-', '_')}_IMAGE"


def parse_env(text: str, source: str = str(ENV)) -> dict[str, Pin]:
    pins: dict[str, Pin] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = ENV_LINE.fullmatch(line)
        if not match:
            raise PinError(f"{source}:{number}: unexpected line: {line}")
        key = match["key"]
        if key in pins:
            raise PinError(f"{source}:{number}: duplicate variable {key}")
        pins[key] = parse_pin(key, match["image"])
    if not pins:
        raise PinError(f"{source}: no images found")
    return pins


def render_env(lock: dict[str, Any]) -> str:
    """The generator of infra/locks/images.env: one line per system, lock order."""
    lines = [ENV_HEADER]
    for system in lock["systems"]:
        lines.append(f"{env_key(system['id'])}={system['image']}")
    return "\n".join(lines) + "\n"


def docker_resolver(reference: str) -> str:
    """Digest of a reference as the registry reports it, via buildx imagetools."""
    error = ""
    for attempt in range(ATTEMPTS):
        result = subprocess.run(
            ["docker", "buildx", "imagetools", "inspect", reference],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                if line.startswith("Digest:"):
                    return line.split()[1]
            raise PinError(f"{reference}: imagetools printed no digest")
        error = result.stderr.strip()
        if "not found" in error.lower():
            raise NotFound(f"{reference}: {error}")
        if attempt + 1 < ATTEMPTS:
            time.sleep(5 * (attempt + 1))
    raise PinError(f"{reference}: registry lookup failed {ATTEMPTS} times: {error}")


def verify(
    pins: dict[str, Pin],
    resolve: Resolver,
    base: dict[str, Pin] | None = None,
    all_tags: bool = False,
) -> tuple[list[str], list[str]]:
    """Problems and notes. Every digest must exist; new or changed pins and,
    with all_tags, every pin must also be what its tag resolves to now."""
    problems: list[str] = []
    notes: list[str] = []
    for key, pin in pins.items():
        try:
            found = resolve(pin.by_digest)
        except NotFound:
            problems.append(
                f"{key}: recorded digest {pin.digest} of {pin.tagged} is no longer "
                "in the registry; re-pin it (./leonaid repin-images --image "
                f"{key_to_id(key)})"
            )
            continue
        if found != pin.digest:
            problems.append(f"{key}: {pin.by_digest} resolves to {found}")
            continue
        changed = base is not None and (key not in base or base[key].image != pin.image)
        if not (all_tags or changed):
            continue
        try:
            current = resolve(pin.tagged)
        except NotFound:
            problems.append(f"{key}: tag {pin.tagged} is not in the registry")
            continue
        if current == pin.digest:
            continue
        reason = "this change pins" if changed else "recorded"
        problems.append(
            f"{key}: {pin.tagged} now resolves to {current}, but {reason} "
            f"{pin.digest}; re-pin it (./leonaid repin-images --image {key_to_id(key)})"
        )
    if base is not None:
        changed_keys = sorted(
            key
            for key, pin in pins.items()
            if key not in base or base[key].image != pin.image
        )
        notes.append(
            "tag checked for changed pins: " + (", ".join(changed_keys) or "none")
        )
    return problems, notes


def key_to_id(key: str) -> str:
    return key.removesuffix("_IMAGE").lower().replace("_", "-")


def candidate_files(root: Path) -> list[Path]:
    """Tracked files when root is a Git checkout, otherwise every checkout file."""
    try:
        listed = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            check=True,
            capture_output=True,
        ).stdout
        files = [root / name for name in listed.decode().split("\0") if name]
    except (OSError, subprocess.CalledProcessError):
        files = checkout_files(root)
    return [
        path
        for path in files
        if path.is_file()
        and not path.is_symlink()
        and path.relative_to(root).parts[0] not in HISTORICAL
    ]


def detect(
    lock: dict[str, Any], resolve: Resolver, only: Iterable[str] = ()
) -> list[Change]:
    systems = {system["id"]: system for system in lock["systems"]}
    wanted = list(dict.fromkeys(only)) or list(systems)
    unknown = [name for name in wanted if name not in systems]
    if unknown:
        raise PinError(
            f"unknown system(s) {', '.join(unknown)}; known: {', '.join(systems)}"
        )
    changes: list[Change] = []
    for system_id in wanted:
        pin = parse_pin(system_id, systems[system_id]["image"])
        if systems[system_id].get("digest") != pin.digest:
            raise PinError(f"{system_id}: digest field differs from image in {LOCK}")
        current = resolve(pin.tagged)
        if current != pin.digest:
            changes.append(Change(system_id, pin.tagged, pin.digest, current))
    for change in changes:
        sharing = [
            system_id
            for system_id, system in systems.items()
            if system_id != change.system and system.get("digest") == change.old
        ]
        if sharing:
            raise PinError(
                f"{change.system}: digest {change.old} is also pinned by "
                f"{', '.join(sharing)}; re-pin these systems by hand"
            )
    return changes


def apply(root: Path, changes: list[Change]) -> list[Path]:
    """Replace every old digest in the checkout, then regenerate images.env."""
    touched: list[Path] = []
    replacements = [(change.old.encode(), change.new.encode()) for change in changes]
    for path in candidate_files(root):
        data = path.read_bytes()
        updated = data
        for old, new in replacements:
            updated = updated.replace(old, new)
        if updated != data:
            path.write_bytes(updated)
            touched.append(path.relative_to(root))
    lock = json.loads((root / LOCK).read_text(encoding="utf-8"))
    systems = {system["id"]: system for system in lock["systems"]}
    for change in changes:
        system = systems[change.system]
        if system["digest"] != change.new or not system["image"].endswith(
            f"@{change.new}"
        ):
            raise PinError(f"{change.system}: {LOCK} was not rewritten")
    env = root / ENV
    rendered = render_env(lock)
    if env.read_text(encoding="utf-8") != rendered:
        env.write_text(rendered, encoding="utf-8")
        if ENV not in touched:
            touched.append(ENV)
    return sorted(touched)


def summary(changes: list[Change], touched: list[Path]) -> str:
    lines = [
        "Upstream rebuilt these pinned tags; the version stays, the digest moves.",
        "",
        "| System | Tag | Old digest | New digest |",
        "|---|---|---|---|",
    ]
    for change in changes:
        lines.append(
            f"| {change.system} | `{change.tagged}` | `{change.old}` | `{change.new}` |"
        )
    lines += ["", "Rewritten files:", ""]
    lines += [f"- `{path}`" for path in touched]
    return "\n".join(lines) + "\n"


def read_base(path: str | None) -> dict[str, Pin] | None:
    if path is None:
        return None
    return parse_env(Path(path).read_text(encoding="utf-8"), path)


def main(argv: list[str] | None = None, resolve: Resolver = docker_resolver) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("verify", help="check pins against the registry")
    check.add_argument("root", type=Path)
    check.add_argument(
        "--base-env",
        help="images.env of the base revision; pins that differ need a current tag",
    )
    check.add_argument(
        "--all-tags", action="store_true", help="every tag must resolve to its pin"
    )
    repin = commands.add_parser("repin", help="move drifted pins to the current digest")
    repin.add_argument("root", type=Path)
    repin.add_argument(
        "--image",
        action="append",
        default=[],
        metavar="SYSTEM",
        help="lock system id (for example postgres); repeatable; default: all",
    )
    repin.add_argument("--summary", type=Path, help="write a Markdown change summary")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "verify":
            pins = parse_env((root / ENV).read_text(encoding="utf-8"))
            problems, notes = verify(
                pins, resolve, read_base(args.base_env), args.all_tags
            )
            for note in notes:
                print(f"image-digest: {note}")
            for problem in problems:
                print(f"image-digest: ERROR: {problem}", file=sys.stderr)
            if problems:
                return 1
            scope = "and tags " if args.all_tags else ""
            print(
                f"image-digest: OK: {len(pins)} recorded digests {scope}resolve in the registry"
            )
            return 0
        lock = json.loads((root / LOCK).read_text(encoding="utf-8"))
        only = [
            key_to_id(name) if name.endswith("_IMAGE") else name for name in args.image
        ]
        changes = detect(lock, resolve, only)
        touched = apply(root, changes) if changes else []
        for change in changes:
            print(f"repin: {change.tagged}: {change.old} -> {change.new}")
        for path in touched:
            print(f"repin: rewrote {path}")
        if not changes:
            print("repin: OK: every checked tag still resolves to its pinned digest")
        if args.summary is not None and changes:
            args.summary.write_text(summary(changes, touched), encoding="utf-8")
        return 0
    except PinError as error:
        print(f"{args.command}: ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
