"""Job-local Compose fixture: build once, restore stopped test volumes between leaves.

The snapshot is synthetic, private and tied to this process and these exact images.
It is not a backup/recovery acceptance test or a persistent CI data cache.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import signal
import subprocess
import tempfile
import time


class SharedStack:
    def __init__(
        self, root: Path, kind: str, output=None, directory: Path | None = None
    ):
        self.root = root.resolve()
        self.kind = kind
        self.output = output
        self.directory = directory or Path(
            tempfile.mkdtemp(prefix="leonaid-test-stack-")
        )
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        profile = self.directory / "services.yml"
        profile.write_text(
            (self.root / "tools/testing/survey-runtime.yml").read_text()
            if kind == "survey"
            else "services: {}\n"
        )
        self.project = "leonaid-shared-" + secrets.token_hex(8)
        self.token = secrets.token_hex(32)
        self.owned = False
        self.ready = False
        self.used = False
        self.volumes: list[str] = []
        self.env = dict(
            os.environ,
            LEONAID_HTTP_PORT="8080",
            LEONAID_HTTPS_PORT="8443",
            TWENTY_INTEGRATION_API_KEY="",
        )
        self.env.pop("LEONAID_FRESH_LOGIN_SECONDS", None)
        self.compose = [
            "docker",
            "compose",
            "--project-name",
            self.project,
            "--env-file",
            str(self.root / ".env.local"),
            "--file",
            str(self.root / "infra/compose/compose.yml"),
            "--file",
            str(self.directory / "compose.yml"),
            "--file",
            str(profile),
            "--profile",
            "dev-mail",
        ]
        locks = dict(
            line.split("=", 1)
            for line in (self.root / "infra/locks/images.env").read_text().splitlines()
            if line and not line.startswith("#")
        )
        self.alpine = locks["ALPINE_IMAGE"].strip("\"'")

    def call(self, args, *, capture=False):
        return subprocess.run(
            args,
            cwd=self.root,
            env=self.env,
            check=True,
            stdout=subprocess.PIPE if capture else self.output,
            stderr=self.output,
            text=True,
        ).stdout

    def inventory(self, resource):
        commands = {
            "containers": ["ps", "-aq"],
            "volumes": ["volume", "ls", "-q"],
            "networks": ["network", "ls", "-q"],
        }
        return sorted(
            self.call(
                [
                    "docker",
                    *commands[resource],
                    "--filter",
                    f"label=com.docker.compose.project={self.project}",
                ],
                capture=True,
            ).split()
        )

    def initialize(self):
        start = time.monotonic()
        # All three read-only guards precede any mutation, including network reservation.
        for resource in ("containers", "volumes", "networks"):
            if self.inventory(resource):
                raise RuntimeError(
                    f"Refusing existing {resource} for shared test project"
                )
        self.call(
            [
                "python3",
                "tools/surveys/network_override.py",
                str(self.directory / "compose.yml"),
            ]
        )
        self.owned = True
        config = self.call(
            [*self.compose, "--profile", "*", "config", "--format", "json"],
            capture=True,
        )
        for name, volume in json.loads(config)["volumes"].items():
            if (
                volume.get("external", False)
                or volume.get("name") != f"{self.project}_{name}"
            ):
                raise RuntimeError(
                    "Shared fixtures require exclusively project-owned volumes"
                )
        subprocess.run(
            [
                "python3",
                str(self.root / "tools/testing/reserve_compose_networks.py"),
                self.project,
                str(self.directory / "compose.yml"),
            ],
            input=config,
            text=True,
            check=True,
            stdout=self.output,
            stderr=self.output,
        )
        # Ordinary Survey leaves never start the PWA; journeys explicitly needs it.
        targets = (
            ["api", "worker", "proxy", "web", "public", "survey-validator"]
            if self.kind == "survey"
            else []
        )
        self.call([*self.compose, "build", *targets])
        fixture = self.env.get("LEONAID_CI_FIXTURE")
        if fixture:
            self.import_fixture(Path(fixture))
            self.write_context()
            self.ready = True
            print(
                f"shared-stack: prepared fixture {time.monotonic() - start:.1f}s; private volumes and networks ready",
                flush=True,
                file=self.output,
            )
            return
        self.call(
            [
                *self.compose,
                "up",
                "--no-build",
                "--detach",
                "--wait",
                "--wait-timeout",
                "420",
                *(
                    ["core-postgres", "rustfs"]
                    if self.env.get("LEONAID_FIXTURE_BUILD") == "1"
                    else ["api"]
                ),
                "twenty-worker",
                "mailpit",
                *(["seaweedfs"] if self.kind == "documents" else []),
            ]
        )
        if self.env.get("LEONAID_FIXTURE_BUILD") == "1":
            # A template contains schema, not API startup side effects. Run the
            # real migrations directly so unrelated request code is not an input.
            self.call(
                [
                    *self.compose,
                    "run",
                    "--rm",
                    "--no-deps",
                    "--entrypoint",
                    "alembic",
                    "api",
                    "upgrade",
                    "head",
                ]
            )
        if self.kind in {"golden", "documents"}:
            self.call(
                [
                    *self.compose,
                    "run",
                    "--rm",
                    "--no-deps",
                    "--user",
                    f"{os.getuid()}:{os.getgid()}",
                    "--env-from-file",
                    str(self.root / ".env.local"),
                    "--env",
                    "PYTHONPATH=/repo:/workspace/src",
                    "--volume",
                    f"{self.root}:/repo:ro",
                    "--volume",
                    f"{self.directory}:/proof",
                    "--workdir",
                    "/repo",
                    "--entrypoint",
                    "python",
                    "api",
                    "tools/twenty/provision.py",
                    "apply",
                    "--token-output",
                    "/proof/integration.env",
                ]
            )
            key = (
                (self.directory / "integration.env")
                .read_text()
                .strip()
                .split("=", 1)[1]
            )
            if len(key) < 32:
                raise RuntimeError("Missing restricted Twenty integration key")
            self.env["TWENTY_INTEGRATION_API_KEY"] = key
            self.call(
                [
                    "/bin/sh",
                    "tools/typst/render_golden.sh",
                    str(self.root),
                    str(self.directory / "pdfs"),
                    self.project + "-api",
                ]
            )
        # Schema and scheduled jobs now exist; keep repeated upgrades/registration
        # out of functional leaves that always restore this exact fixture.
        self.compose += ["--file", str(self.root / "tools/testing/shared-runtime.yml")]
        # Create remaining containers/volumes without running application workers.
        self.call([*self.compose, "create", "--no-build", "proxy", "worker", "mailpit"])
        # Preserve the initial persisted queues/databases with a normal stop window.
        self.call([*self.compose, "--profile", "*", "stop", "--timeout", "30"])
        self.volumes = self.inventory("volumes")
        if not self.volumes:
            raise RuntimeError("Missing shared fixture volumes")
        if self.env.get("LEONAID_FIXTURE_BUILD") == "1":
            queue = self.project + "_twenty-redis-data"
            if queue not in self.volumes:
                raise RuntimeError("Missing owned fixture queue volume")
            # Do not replay overdue cron jobs from the time the template was
            # created. Functional leaves enqueue their own work; cold installation
            # tests retain the normal scheduler registration and persisted queues.
            self.call(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--network",
                    "none",
                    "--mount",
                    f"type=volume,src={queue},dst=/queues",
                    self.alpine,
                    "find",
                    "/queues",
                    "-mindepth",
                    "1",
                    "-delete",
                ]
            )
        self.copy_volumes("save")
        self.write_context()
        self.ready = True
        print(
            f"shared-stack: setup {time.monotonic() - start:.1f}s; images and initialized volumes ready",
            flush=True,
            file=self.output,
        )

    def write_context(self):
        values = {
            "project": self.project,
            "integration_key": self.env["TWENTY_INTEGRATION_API_KEY"],
            "shared_root": str(self.root),
            "shared_token": self.token,
        }
        (self.directory / "context.env").write_text(
            "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items())
        )
        (self.directory / "context.env").chmod(0o600)

    def import_fixture(self, directory):
        if __package__:
            from .ci_fixture import environment, validate
        else:
            from ci_fixture import environment, validate
        if (self.root / ".env.local").read_text() != environment(self.root):
            raise RuntimeError("Prepared CI fixture requires its synthetic environment")
        metadata = validate(self.root, directory)
        self.env["TWENTY_INTEGRATION_API_KEY"] = metadata["integrationKey"]
        self.compose += ["--file", str(self.root / "tools/testing/shared-runtime.yml")]
        # Volumes are cheap to create directly. Do not pull/start unused services
        # just to materialize their storage (for example SeaweedFS in an E2E job).
        # Compose receives its normal ownership labels and creates only the leaf's
        # requested services later. The template itself is never mounted writable.
        for name in metadata["volumes"]:
            self.call(
                [
                    "docker",
                    "volume",
                    "create",
                    "--label",
                    f"com.docker.compose.project={self.project}",
                    "--label",
                    f"com.docker.compose.volume={name}",
                    self.project + "_" + name,
                ]
            )
        self.volumes = self.inventory("volumes")
        expected = [self.project + "_" + name for name in metadata["volumes"]]
        if self.volumes != expected:
            raise RuntimeError(
                "Prepared fixture volume inventory does not match Compose"
            )
        for name in metadata["files"]:
            target = self.directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(directory / name, target)
        self.copy_volumes("restore")

    def copy_volumes(self, mode):
        # No live process may hold a database, queue or storage file during copying.
        running = self.call(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
            ],
            capture=True,
        )
        if running.strip():
            raise RuntimeError(
                f"Refusing fixture reset: active container IDs {running.split()}"
            )
        current = self.inventory("volumes")
        if current != self.volumes:
            raise RuntimeError(
                f"Refusing fixture reset: volume inventory changed; expected {self.volumes}, actual {current}"
            )
        args = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--volume",
            f"{self.directory}:/fixture",
        ]
        for index, volume in enumerate(self.volumes):
            args += ["--mount", f"type=volume,src={volume},dst=/state/{index}"]
        # Names are numeric indices from the guarded inventory, never external paths.
        script = (
            'for d in /state/*; do tar -C "$d" -cf "/fixture/volume-${d##*/}.tar" .; done'
            if mode == "save"
            else 'for d in /state/*; do test -s "/fixture/volume-${d##*/}.tar"; find "$d" -mindepth 1 -delete; tar -C "$d" -xf "/fixture/volume-${d##*/}.tar"; done'
        )
        self.call([*args, self.alpine, "sh", "-eu", "-c", script])

    def prepare(self):
        # Atomic directory creation also excludes a borrowed leaf in another process.
        lease = self.directory / "in-use"
        lease.mkdir()
        try:
            return self._prepare()
        finally:
            lease.rmdir()

    def _prepare(self):
        if not self.ready:
            self.initialize()
        elif self.used:
            start = time.monotonic()
            self.call([*self.compose, "--profile", "*", "stop", "--timeout", "5"])
            self.copy_volumes("restore")
            print(
                f"shared-stack: data reset {time.monotonic() - start:.1f}s",
                flush=True,
                file=self.output,
            )
        self.used = True
        return {
            "LEONAID_TEST_STACK": str(self.directory),
            "LEONAID_TEST_STACK_TOKEN": self.token,
        }

    def close(self):
        try:
            if self.owned:
                self.call(
                    [
                        *self.compose,
                        "--profile",
                        "*",
                        "down",
                        "--volumes",
                        "--remove-orphans",
                    ]
                )
                for resource in ("containers", "volumes", "networks"):
                    if self.inventory(resource):
                        raise RuntimeError(
                            f"Owned {resource} remain after shared test group"
                        )
                print(
                    "shared-stack: owned containers, volumes and networks removed",
                    flush=True,
                    file=self.output,
                )
        finally:
            if self.directory.exists():
                shutil.rmtree(self.directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reuse", action="store_true", help="Reuse a private checkout-local fixture"
    )
    parser.add_argument(
        "--stop",
        action="store_true",
        help="Remove only the cached local test environment",
    )
    parser.add_argument(
        "kind", nargs="?", default="documents", choices=["core", "golden", "documents"]
    )
    parser.add_argument("scripts", nargs="*")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    cache = None
    if args.reuse or args.stop:
        from local_stack import LocalStack

        cache = LocalStack(root, stop=args.stop)
        if args.stop:
            cache.close()
            return 0
        stack = cache.stack
    else:
        stack = SharedStack(root, args.kind)
    if not args.scripts:
        if cache:
            cache.close()
        else:
            stack.close()
        parser.error("At least one test script is required")
    # The child receives the same terminal/process-group signal; wait for its trap
    # before removing the shared environment. During setup, finally handles cleanup.
    child = None

    def stop(signum, frame):
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait()
        raise KeyboardInterrupt

    previous = {
        sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        for script in args.scripts:
            env = dict(os.environ, **stack.prepare())
            print(f"shared-stack: testing {script}", flush=True)
            start = time.monotonic()
            child = subprocess.Popen(
                ["/bin/sh", str(root / script), str(root)], cwd=root, env=env
            )
            code = child.wait()
            print(
                f"shared-stack: {script} {time.monotonic() - start:.1f}s, exit {code}",
                flush=True,
            )
            if code:
                return code
        return 0
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        if cache:
            cache.close()
        else:
            stack.close()


if __name__ == "__main__":
    raise SystemExit(main())
