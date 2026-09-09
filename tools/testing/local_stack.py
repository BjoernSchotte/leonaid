"""Private, checkout-local test fixture cache; never adopts a development stack."""

import fcntl
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

if __package__:
    from .shared_stack import SharedStack
else:
    from shared_stack import SharedStack


def fingerprints(root: Path) -> tuple[str, str]:
    names = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root,
        )
        .decode()
        .split("\0")
    )
    data = hashlib.sha256()
    build = hashlib.sha256()
    for name in sorted(set(names + [".env.local"])):
        baseline = name.startswith(
            (
                "migrations/",
                "tools/twenty/",
                "tools/testing/",
                "tests/fixtures/golden/",
                "src/leonaid/adapters/typst/",
            )
        ) or name in {
            ".env.local",
            "infra/compose/compose.yml",
            "infra/locks/images.env",
            "infra/compose/start-api.sh",
            "tools/typst/render_golden.sh",
        }
        image = name.startswith(
            ("src/", "apps/", "packages/", "infra/", "migrations/")
        ) or name in {
            ".dockerignore",
            "package.json",
            "bun.lock",
            "pyproject.toml",
            "uv.lock",
            "alembic.ini",
        }
        if not baseline and not image:
            continue
        path = root / name
        content = path.read_bytes() if path.is_file() else b"<missing>"
        for digest, selected in ((data, baseline), (build, image)):
            if selected:
                digest.update(name.encode() + b"\0" + hashlib.sha256(content).digest())
    return data.hexdigest(), build.hexdigest()


class LocalStack:
    def __init__(self, root: Path, *, stop=False, output=None):
        self.output = output
        self.root = root.resolve()
        self.directory = self.root / ".local/test-stack"
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.directory.chmod(0o700)
        self.lock = (self.directory / "run.lock").open("a")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError(
                "Another local test owns this checkout's fixture; no reset was performed"
            ) from None
        self.data_hash, self.build_hash = fingerprints(self.root)
        self.stack = None
        self.state_path = self.directory / "owner.json"
        try:
            state = (
                json.loads(self.state_path.read_text())
                if self.state_path.exists()
                else None
            )
            if state:
                if (
                    state.get("schemaVersion") != 1
                    or state.get("root") != str(self.root)
                    or not re.fullmatch(
                        r"leonaid-shared-[0-9a-f]{16}", state.get("project", "")
                    )
                ):
                    raise RuntimeError(
                        "Invalid local test owner; refusing Docker mutations"
                    )
                self.stack = SharedStack(
                    self.root,
                    "documents",
                    output=self.output,
                    directory=self.directory / "data",
                )
                self.stack.project = state["project"]
                self.stack.compose[self.stack.compose.index("--project-name") + 1] = (
                    self.stack.project
                )
                if not stop and (self.stack.directory / "in-use").exists():
                    raise RuntimeError(
                        "Active or interrupted test lease; no reset performed. Use ./leonaid test-env-stop to remove an abandoned fixture"
                    )
                self.stack.owned = True
                self.stack.ready = state.get("ready", False)
                self.stack.used = self.stack.ready
                self.stack.token = state.get("token", self.stack.token)
                self.stack.volumes = state.get("volumes", [])
                self.stack.env["TWENTY_INTEGRATION_API_KEY"] = state.get(
                    "integrationKey", ""
                )
                self.stack.compose += [
                    "--file",
                    str(self.root / "tools/testing/shared-runtime.yml"),
                ]
                if (
                    stop
                    or not self.stack.ready
                    or state.get("dataHash") != self.data_hash
                ):
                    self.discard()
                else:
                    if self.stack.inventory("volumes") != self.stack.volumes:
                        raise RuntimeError(
                            "Local fixture resources changed; run ./leonaid test-env-stop before retrying"
                        )
                    rebuild = state.get("buildHash") != self.build_hash
                    if not rebuild:
                        try:
                            self.stack.call(
                                [
                                    "docker",
                                    "image",
                                    "inspect",
                                    "--format",
                                    "{{.Id}}",
                                    *[
                                        f"{self.stack.project}-{name}"
                                        for name in (
                                            "api",
                                            "worker",
                                            "pwa",
                                            "web",
                                            "public",
                                            "proxy",
                                            "survey-validator",
                                        )
                                    ],
                                ],
                                capture=True,
                            )
                        except subprocess.CalledProcessError:
                            rebuild = True
                    if rebuild:
                        print(
                            "local-test-stack: application inputs changed; rebuilding cached images, retaining the data fixture",
                            flush=True,
                            file=self.output,
                        )
                        self.stack.call([*self.stack.compose, "build"])
            if stop:
                return
            if self.stack is None:
                self.stack = SharedStack(
                    self.root,
                    "documents",
                    output=self.output,
                    directory=self.directory / "data",
                )
                self.save()  # Record ownership before any Docker mutation, including interrupted setup.
            else:
                print(
                    "local-test-stack: reusing this checkout's initialized test fixture",
                    flush=True,
                    file=self.output,
                )
        except BaseException:
            self.lock.close()
            raise

    def save(self):
        stack = self.stack
        state = {
            "schemaVersion": 1,
            "root": str(self.root),
            "project": stack.project,
            "token": stack.token,
            "ready": stack.ready,
            "volumes": stack.volumes,
            "integrationKey": stack.env["TWENTY_INTEGRATION_API_KEY"],
            "dataHash": self.data_hash,
            "buildHash": self.build_hash,
        }
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state))
        temporary.chmod(0o600)
        temporary.replace(self.state_path)

    def discard(self):
        # Labels, not a possibly changed Compose file, identify the old owned
        # resources. Never follow resource names supplied by a new checkout config.
        for resource, command in (
            ("containers", ["docker", "rm", "--force"]),
            ("volumes", ["docker", "volume", "rm"]),
            ("networks", ["docker", "network", "rm"]),
        ):
            names = self.stack.inventory(resource)
            if names:
                self.stack.call([*command, *names])
            if self.stack.inventory(resource):
                raise RuntimeError("Owned local test resources remain")
        shutil.rmtree(self.stack.directory)
        self.state_path.unlink(missing_ok=True)
        self.stack = None
        print(
            "local-test-stack: owned test environment removed",
            flush=True,
            file=self.output,
        )

    def close(self):
        try:
            if self.stack is not None:
                self.save()
                if self.stack.ready:
                    print(
                        "local-test-stack: fixture retained; ./leonaid test-env-stop removes it",
                        flush=True,
                        file=self.output,
                    )
                else:
                    self.discard()
        finally:
            self.lock.close()
