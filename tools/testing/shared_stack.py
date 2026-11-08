"""Job-local Compose fixture: build once, restore stopped test volumes between leaves.

The snapshot is synthetic, private and tied to this process and these exact images.
It is not a backup/recovery acceptance test or a persistent CI data cache.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
from pathlib import Path
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time


if __package__:
    from . import parallel_stacks
else:
    import parallel_stacks


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
        # Set by the local fixture cache after it validated the entry it holds.
        self.fixture_metadata: dict | None = None
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

    def remove_owned(self):
        """Force-remove everything labelled with this project; return what was left.

        Containers go first (including stopped one-off `compose run`
        containers) because they hold networks and volumes. Only objects that
        carry this project's Compose label are touched.
        """
        found = {}
        for resource, command in (
            ("containers", ["docker", "rm", "--force", "--volumes"]),
            ("networks", ["docker", "network", "rm"]),
            ("volumes", ["docker", "volume", "rm", "--force"]),
        ):
            names = self.inventory(resource)
            if names:
                found[resource] = names
                self.call([*command, *names])
            if self.inventory(resource):
                raise RuntimeError(f"Owned {resource} could not be removed")
        return found

    def build_images(self, targets):
        """Build this project's images, reusing content-hash tags of all checkouts.

        `leonaid-local/<service>:<hash>` covers every build input
        (tools/testing/image_tags.py); a hit is only tagged as
        `<project>-<service>`, a miss is built and recorded. CI builds without
        recording, so job disks keep freeing images at teardown.
        """
        if __package__:
            from . import image_tags
        else:
            import image_tags
        config = json.loads(
            self.call([*self.compose, "config", "--format", "json"], capture=True)
        )
        # The effective build sections, as this project's Compose files define them.
        builds = image_tags.effective_builds(config)
        services = [
            name
            for name in (targets or sorted(config["services"]))
            if "build" in config["services"].get(name, {})
        ]
        missing = image_tags.adopt(self.root, self.project, builds, services)
        if missing:
            self.call([*self.compose, "build", *missing])
            if not self.env.get("CI"):
                # Recorded under the pre-build hash, only if inputs did not change.
                image_tags.record(self.root, self.project, builds, missing)

    def remove_built_images(self):
        """Remove the `<project>-<service>` images Compose built for this project."""
        tags = self.call(
            [
                "docker",
                "image",
                "ls",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
                "--format",
                "{{.Repository}}:{{.Tag}}",
            ],
            capture=True,
        ).split()
        for tag in tags:
            if tag.startswith(self.project + "-") and (
                subprocess.run(
                    ["docker", "image", "rm", tag],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                ).returncode
                != 0
            ):
                print(
                    f"shared-stack: built image {tag} is still in use; kept",
                    flush=True,
                    file=self.output,
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
        self.build_images(targets)
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
            from .ci_fixture import is_synthetic, validate
        else:
            from ci_fixture import is_synthetic, validate
        if not is_synthetic(self.root, (self.root / ".env.local").read_text()):
            raise RuntimeError("Prepared CI fixture requires its synthetic environment")
        metadata = (
            self.fixture_metadata
            if self.fixture_metadata is not None
            else validate(self.root, directory)
        )
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

    def active_containers(self):
        # `docker ps` without -a lists running, restarting and paused containers.
        return self.call(
            [
                "docker",
                "ps",
                "-q",
                "--filter",
                f"label=com.docker.compose.project={self.project}",
            ],
            capture=True,
        ).split()

    def describe(self, containers):
        result = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.Name}} status={{.State.Status}} restarts={{.RestartCount}} "
                'oneoff={{index .Config.Labels "com.docker.compose.oneoff"}} '
                "policy={{.HostConfig.RestartPolicy.Name}}",
                *containers,
            ],
            env=self.env,
            capture_output=True,
            text=True,
        )
        return "; ".join(result.stdout.split("\n")).strip("; ") or str(containers)

    def quiesce(self, timeout=60):
        """Stop every container of the project, or fail closed after timeout.

        `compose stop` covers only the service containers that exist at that
        moment. A container in restart backoff (restart: unless-stopped after
        a crash) is not running while Compose stops it and is restarted by the
        daemon afterwards; a one-off left by a test script is no service
        container at all. Both are stopped explicitly here; the manual-stop
        flag then prevents further restarts.
        """
        deadline = time.monotonic() + timeout
        while active := self.active_containers():
            details = self.describe(active)
            if time.monotonic() > deadline:
                raise RuntimeError(
                    f"Refusing fixture reset: active containers after {timeout}s: {details}"
                )
            print(
                f"shared-stack: stopping lingering containers: {details}",
                flush=True,
                file=self.output,
            )
            # A container may vanish (--rm) between listing and stopping.
            subprocess.run(
                ["docker", "stop", "--timeout", "5", *active],
                env=self.env,
                stdout=subprocess.DEVNULL,
                stderr=self.output,
            )
            time.sleep(1)

    def copy_volumes(self, mode):
        # No live process may hold a database, queue or storage file during copying.
        self.quiesce()
        current = self.inventory("volumes")
        if current != self.volumes:
            raise RuntimeError(
                f"Refusing fixture reset: volume inventory changed; expected {self.volumes}, actual {current}"
            )
        # host-write-user: root reads service-owned volumes; save hands the archives to the host user
        args = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--env",
            f"FIXTURE_OWNER={os.getuid()}:{os.getgid()}",
            "--volume",
            f"{self.directory}:/fixture",
        ]
        for index, volume in enumerate(self.volumes):
            args += ["--mount", f"type=volume,src={volume},dst=/state/{index}"]
        # Names are numeric indices from the guarded inventory, never external paths.
        script = (
            'for d in /state/*; do tar -C "$d" -cf "/fixture/volume-${d##*/}.tar" .; '
            'chown "$FIXTURE_OWNER" "/fixture/volume-${d##*/}.tar"; done'
            if mode == "save"
            else 'for d in /state/*; do test -s "/fixture/volume-${d##*/}.tar"; find "$d" -mindepth 1 -delete; tar -C "$d" -xf "/fixture/volume-${d##*/}.tar"; done'
        )
        self.call([*args, self.alpine, "sh", "-eu", "-c", script])
        # Fail closed if anything started while the copy ran.
        if active := self.active_containers():
            raise RuntimeError(
                f"Fixture {mode} raced with started containers: {self.describe(active)}"
            )

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
                down_failed = None
                try:
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
                except subprocess.CalledProcessError as error:
                    down_failed = error
                # Runs even when `down` failed, so no failure path leaks.
                leftovers = self.remove_owned()
                self.remove_built_images()
                if down_failed is not None:
                    raise down_failed
                if leftovers:
                    raise RuntimeError(
                        "Owned resources remained after shared test group and were "
                        f"removed: {leftovers}"
                    )
                print(
                    "shared-stack: owned containers, volumes and networks removed",
                    flush=True,
                    file=self.output,
                )
        finally:
            if self.directory.exists():
                shutil.rmtree(self.directory)


# Grace period between SIGTERM and SIGKILL for a cancelled leaf.
KILL_AFTER_SECONDS = 30


def exit_status(code):
    """A signal-terminated child reports -N; report it like a shell (128+N)."""
    return 128 - code if code < 0 else code


class LeafRunner:
    """Run leaves over one or more stacks, one leaf at a time per stack.

    - cancel() (INT/TERM) stops scheduling: no leaf starts afterwards, running
      leaves are terminated, and run() returns only after every worker ended,
      so the caller removes the stacks with nothing left running on them.
    - A stack whose prepare() (reset/initialization) fails is retired: its
      leaf goes back to the queue for a healthy stack, and the failure fails
      the suite. Leaves left without any healthy stack fail.
    - Every leaf taken from the queue ends with a result, whatever happens
      while running or reporting it.
    """

    def __init__(self, root, stacks, scripts, keep_going, output_lock):
        self.root = root
        self.stacks = stacks
        self.scripts = scripts
        self.keep_going = keep_going
        self.output_lock = output_lock
        self.parallel = len(stacks) > 1
        self.pending = queue.Queue()
        for script in scripts:
            self.pending.put(script)
        self.results = []
        self.problems = []
        self.cancelled = threading.Event()
        self.stopped = threading.Event()
        self.children_lock = threading.Lock()
        self.children = set()
        self.healthy = len(stacks)
        self.busy = 0
        self.kill_timer = None
        self.state_lock = threading.Lock()

    def say(self, text):
        with self.output_lock:
            print(text, flush=True)

    def cancel(self):
        with self.children_lock:
            first = not self.cancelled.is_set()
            self.cancelled.set()
            for child in list(self.children):
                if child.poll() is None:
                    child.terminate()
        if first:
            # A leaf that ignores SIGTERM is killed after the grace period.
            self.kill_timer = threading.Timer(KILL_AFTER_SECONDS, self.kill_remaining)
            self.kill_timer.daemon = True
            self.kill_timer.start()

    def kill_remaining(self):
        with self.children_lock:
            for child in list(self.children):
                if child.poll() is None:
                    child.kill()

    def start_leaf(self, script, env, log):
        """Popen unless cancelled; atomic with cancel()'s view of children."""
        with self.children_lock:
            if self.cancelled.is_set():
                return None
            child = subprocess.Popen(
                ["/bin/sh", str(self.root / script), str(self.root)],
                cwd=self.root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT if log is not None else None,
            )
            self.children.add(child)
            return child

    def run_leaf(self, stack, script):
        """Return the leaf's exit status, or None if the stack is broken."""
        start = time.monotonic()
        code = 1
        log = tempfile.TemporaryFile() if self.parallel else None
        try:
            try:
                env = dict(os.environ, **stack.prepare())
            except Exception as error:
                self.say(
                    f"shared-stack: {getattr(stack, 'project', 'stack')} failed to "
                    f"reset before {script}: {error}; retiring this stack"
                )
                code = None
                return None
            self.say(
                f"shared-stack: testing {script} on {getattr(stack, 'project', 'the stack')}"
            )
            child = self.start_leaf(script, env, log)
            if child is None:
                code = 130
                return code
            try:
                code = exit_status(child.wait())
            finally:
                with self.children_lock:
                    self.children.discard(child)
            return code
        except Exception as error:
            code = 1
            self.say(f"shared-stack: {script}: {error}")
            return code
        finally:
            try:
                with self.output_lock:
                    if log is not None:
                        log.seek(0)
                        # Decoded with replacement: logs (and CI artifacts
                        # built from them) stay valid UTF-8 whatever a leaf
                        # printed.
                        sys.stdout.write(log.read().decode("utf-8", "replace"))
                        sys.stdout.flush()
                    if code is not None:
                        print(
                            f"shared-stack: {script} {time.monotonic() - start:.1f}s, "
                            f"exit {code}",
                            flush=True,
                        )
            except Exception as error:  # Reporting never drops a result.
                self.problems.append(f"output of {script}: {error}")
            finally:
                if log is not None:
                    log.close()

    def worker(self, stack):
        try:
            while not (self.stopped.is_set() or self.cancelled.is_set()):
                try:
                    script = self.pending.get(timeout=0.2)
                except queue.Empty:
                    # Stay available while another worker may still requeue
                    # a leaf from a stack that breaks.
                    with self.state_lock:
                        if self.busy == 0:
                            return
                    continue
                with self.state_lock:
                    self.busy += 1
                try:
                    code = self.run_leaf(stack, script)
                except BaseException:
                    with self.state_lock:
                        self.busy -= 1
                    raise
                self.leaf_done(stack, script, code)
                if code is None:
                    return
                if code and not self.keep_going:
                    self.stopped.set()
        except Exception as error:
            with self.state_lock:
                self.problems.append(
                    f"worker for {getattr(stack, 'project', '?')}: {error}"
                )
                self.healthy -= 1

    def leaf_done(self, stack, script, code):
        """Record a leaf (or requeue it from a broken stack), then mark idle."""
        with self.state_lock:
            try:
                if code is None:
                    self.problems.append(
                        f"stack {getattr(stack, 'project', '?')} failed to reset"
                    )
                    self.healthy -= 1
                    if self.healthy > 0:
                        self.pending.put(script)
                    else:
                        self.results.append((script, 1))
                else:
                    self.results.append((script, code))
            finally:
                self.busy -= 1

    def run(self):
        threads = [
            threading.Thread(target=self.worker, args=(stack,), daemon=True)
            for stack in self.stacks
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        if self.kill_timer is not None:
            # Every leaf ended; nothing left to kill.
            self.kill_timer.cancel()
        if not (self.cancelled.is_set() or self.stopped.is_set()):
            # Leaves no healthy stack could take.
            while True:
                try:
                    script = self.pending.get_nowait()
                except queue.Empty:
                    break
                self.results.append((script, 1))
                self.problems.append(f"{script}: no healthy stack left")
        return self.results


def run_leaves(root, stacks, scripts, keep_going, output_lock, runner_holder=None):
    """Compatibility wrapper: run and return [(script, exit status)]."""
    runner = LeafRunner(root, stacks, scripts, keep_going, output_lock)
    if runner_holder is not None:
        runner_holder.append(runner)
    return runner.run()


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
        "--keep-going",
        action="store_true",
        help="Run every leaf after a failure; exit with the first failure's code",
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
    extra_stacks = []
    extra_logs = []
    slots = []
    runners = []
    output_lock = threading.Lock()
    received = []

    # Leaves share the terminal/process-group signal. While leaves run, a
    # signal only cancels: no leaf starts afterwards, running ones are
    # terminated, and the stacks are removed after every worker ended. During
    # setup it interrupts, and finally handles cleanup.
    def stop(signum, frame):
        received.append(signum)
        if runners:
            runners[0].cancel()
        else:
            raise KeyboardInterrupt

    previous = {
        sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        count, reason = parallel_stacks.wanted(len(args.scripts))
        fixture = None
        if count > 1:
            if cache is not None:
                fixture = cache.shared_fixture()
            elif os.environ.get("LEONAID_CI_FIXTURE"):
                fixture = (Path(os.environ["LEONAID_CI_FIXTURE"]), None)
            if fixture is None:
                count, reason = 1, "no prepared fixture for additional stacks"
        if count > 1:
            slots = parallel_stacks.take_slots(count - 1)
            if os.environ.get("LEONAID_STACK_SLOTS_DIR") and len(slots) < count - 1:
                reason += f"; {len(slots)} free slot(s) for additional stacks"
                count = 1 + len(slots)
        print(f"shared-stack: {count} stack(s) ({reason})", flush=True)
        for _ in range(count - 1):
            # Setup output is shown only if the stack breaks (see below).
            log = tempfile.TemporaryFile(mode="w+", errors="replace")
            extra_logs.append(log)
            extra = SharedStack(root, args.kind, output=log)
            extra.env["LEONAID_CI_FIXTURE"] = str(fixture[0])
            extra.fixture_metadata = fixture[1]
            extra_stacks.append(extra)
        runner = LeafRunner(
            root, [stack, *extra_stacks], args.scripts, args.keep_going, output_lock
        )
        runners.append(runner)
        results = runner.run()
        if received or runner.cancelled.is_set():
            print("shared-stack: interrupted; no further leaves started", flush=True)
            return 128 + (received[0] if received else signal.SIGTERM)
        failed = sorted(
            ((script, code) for script, code in results if code),
            key=lambda item: args.scripts.index(item[0]),
        )
        for problem in runner.problems:
            print(f"shared-stack: problem: {problem}", flush=True)
        if runner.problems:
            for log in extra_logs:
                log.seek(0)
                sys.stdout.write(log.read())
        if failed:
            print(
                "shared-stack: failed leaves: "
                + ", ".join(f"{script} (exit {code})" for script, code in failed),
                flush=True,
            )
            return failed[0][1]
        # A retired stack or a reporting problem fails the suite as well.
        return 1 if runner.problems else 0
    finally:
        if runners:
            runners[0].cancel()
        for sig, handler in previous.items():
            signal.signal(sig, handler)
        try:
            for extra in extra_stacks:
                extra.close()
        finally:
            for log in extra_logs:
                log.close()
            for slot in slots:
                slot.close()
            if cache:
                cache.close()
            else:
                stack.close()


if __name__ == "__main__":
    raise SystemExit(main())
