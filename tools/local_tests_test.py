"""Local selection, cache invalidation and process ownership regressions."""

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.testing.local_stack import LocalStack, fingerprints


class LocalTests(unittest.TestCase):
    def test_suite_commands_are_the_ci_entry_points(self):
        root = Path(__file__).resolve().parents[1]
        cli = (root / "leonaid").read_text()
        import re

        # E-027: no hand-kept leaf lists; the CI scripts own the suites.
        suites = cli.split("  test-integration | test-e2e | test-emdash)\n")[1]
        self.assertIn('/bin/sh "$root/tools/ci/$suite.sh" "$@"', suites.split(";;")[0])
        for script in ("integration", "e2e"):
            text = (root / f"tools/ci/{script}.sh").read_text()
            self.assertNotIn("tools/backup/", text)
            self.assertNotIn("tools/upgrade/", text)
        # Every survey check mode belongs to exactly one shard of
        # ./leonaid test-surveys.
        shards = cli.split("test_surveys() {\n")[1].split("\n}\n")[0]
        assigned = re.findall(r"\$survey_leaf ([a-z-]+)", shards)
        for loop in re.findall(
            r"for mode in ([a-z -]+); do\n\s+/bin/sh \"\$root/\$survey_leaf\"", shards
        ):
            assigned += loop.split()
        script = (root / "tools/surveys/infrastructure.sh").read_text()
        modes = re.findall(
            r"[a-z-]+", script.split('case "$mode" in\n')[1].split(") ;;")[0]
        )
        self.assertEqual(len(modes), 23)
        self.assertEqual(sorted(assigned), sorted(modes))

    def test_changes_invalidate_only_required_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "src").mkdir()
            (root / "migrations").mkdir()
            app = root / "src/app.py"
            app.write_text("one")
            original = fingerprints(root)
            app.write_text("two")
            changed = fingerprints(root)
            self.assertEqual(original[0], changed[0])
            self.assertNotEqual(original[1], changed[1])
            (root / "migrations/new.py").write_text("migration")
            migrated = fingerprints(root)
            self.assertNotEqual(changed[0], migrated[0])
            (root / ".env.local").write_text("setting=changed")
            self.assertNotEqual(migrated[0], fingerprints(root)[0])

    def test_busy_checkout_refuses_before_reading_or_mutating_docker(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache = root / ".local/test-stack"
            cache.mkdir(parents=True)
            with (cache / "run.lock").open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "from tools.testing.local_stack import LocalStack; from pathlib import Path; LocalStack(Path(__import__('sys').argv[1]))",
                        str(root),
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("no reset was performed", result.stderr)
                self.assertFalse((cache / "owner.json").exists())

    def test_closing_a_retained_fixture_stops_its_containers(self):
        # Real Docker: an idle fixture must not keep services running after the
        # last leaf, while the fixture itself (owner state, volumes) is retained.
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / "infra/locks").mkdir(parents=True)
            shutil.copy(source / "infra/locks/images.env", root / "infra/locks")
            cache = LocalStack(root)
            stack = cache.stack
            assert stack is not None
            container = subprocess.run(
                [
                    "docker",
                    "run",
                    "--detach",
                    "--network",
                    "none",
                    "--label",
                    f"com.docker.compose.project={stack.project}",
                    stack.alpine,
                    "sleep",
                    "600",
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.addCleanup(
                subprocess.run,
                ["docker", "rm", "--force", container],
                capture_output=True,
            )
            stack.ready = True
            cache.close()
            state = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Status}}", container],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            self.assertEqual(state, "exited")
            owner = json.loads((root / ".local/test-stack/owner.json").read_text())
            self.assertTrue(owner["ready"])
            self.assertEqual(owner["project"], stack.project)


class CheckoutIsolationTests(unittest.TestCase):
    """Only the recorded main checkout may address the "leonaid" dev instance."""

    FILES = ("leonaid", "tools/testing/phase.sh", "infra/locks/images.env")

    def make_repository(self, directory: Path) -> tuple[Path, Path]:
        source = Path(__file__).resolve().parents[1]
        main = directory / "main"
        names = [*self.FILES]
        names += [
            path.relative_to(source).as_posix()
            for path in (source / "tools/backup").glob("*.sh")
        ]
        for name in names:
            target = main / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((source / name).read_bytes())
        (main / "leonaid").chmod(0o755)
        (main / ".env.local").write_text(
            "LEONAID_HTTP_PORT=28090\nLEONAID_HTTPS_PORT=28091\n"
        )
        git = ["git", "-C", str(main), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", str(main)], check=True)
        subprocess.run([*git, "add", "leonaid", "tools", "infra"], check=True)
        subprocess.run([*git, "commit", "-qm", "init"], check=True)
        worktree = directory / "worktree"
        subprocess.run(
            [*git, "worktree", "add", "-q", "--detach", str(worktree)], check=True
        )
        return main, worktree

    def record_main(self, main: Path) -> None:
        # What `./leonaid bootstrap --main-instance` writes.
        (main / ".local").mkdir(exist_ok=True)
        (main / ".local/main-instance").write_text(f"{main.resolve()}\n")

    def run_cli(self, checkout: Path, *args: str, **env: str):
        return subprocess.run(
            [str(checkout / "leonaid"), *args],
            capture_output=True,
            text=True,
            env={**os.environ, **env},
        )

    def instance(self, checkout: Path, **env: str) -> dict[str, str]:
        result = self.run_cli(checkout, "local-instance", **env)
        self.assertEqual(result.returncode, 0, result.stderr)
        return dict(line.split("=", 1) for line in result.stdout.splitlines())

    def test_only_the_recorded_main_checkout_is_leonaid(self):
        with tempfile.TemporaryDirectory() as directory:
            main, worktree = self.make_repository(Path(directory))
            # Unrecorded, even the primary checkout fails closed.
            self.assertRegex(self.instance(main)["project"], r"\Aleonaid-wt-[0-9]+\Z")
            self.record_main(main)
            primary = self.instance(main)
            self.assertEqual(primary["project"], "leonaid")
            self.assertEqual(primary["checkout"], "main")
            self.assertEqual(primary["reserved_ports"], "")
            linked = self.instance(worktree)
            self.assertRegex(linked["project"], r"\Aleonaid-wt-[0-9]+\Z")
            self.assertEqual(linked["checkout"], "other")
            self.assertEqual(
                linked["reserved_ports"].split(),
                ["8080", "8443", "28080", "28081", "28090", "28091"],
            )
            # Deterministic per path; another project may be chosen explicitly.
            self.assertEqual(self.instance(worktree)["project"], linked["project"])
            self.assertEqual(
                self.instance(worktree, LEONAID_COMPOSE_PROJECT="leonaid-x")["project"],
                "leonaid-x",
            )
            refused = self.run_cli(
                worktree, "local-instance", LEONAID_COMPOSE_PROJECT="leonaid"
            )
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("names the main development instance", refused.stderr)

    def test_clone_copied_marker_and_failing_git_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            main, worktree = self.make_repository(Path(directory))
            self.record_main(main)
            clone = Path(directory) / "clone"
            subprocess.run(["git", "clone", "-q", str(main), str(clone)], check=True)
            # Even a copied marker names another path.
            (clone / ".local").mkdir()
            (clone / ".local/main-instance").write_text(
                (main / ".local/main-instance").read_text()
            )
            self.assertNotEqual(self.instance(clone)["project"], "leonaid")
            (worktree / ".local").mkdir()
            (worktree / ".local/main-instance").write_text(f"{worktree.resolve()}\n")
            self.assertNotEqual(self.instance(worktree)["project"], "leonaid")
            # git fails (dubious ownership, missing git): still not "leonaid".
            stub = Path(directory) / "bin"
            stub.mkdir()
            (stub / "git").write_text("#!/bin/sh\nexit 128\n")
            (stub / "git").chmod(0o755)
            path = f"{stub}:{os.environ['PATH']}"
            self.assertNotEqual(
                self.instance(worktree, PATH=path)["project"], "leonaid"
            )
            self.assertNotEqual(self.instance(clone, PATH=path)["project"], "leonaid")
            self.assertEqual(self.instance(main, PATH=path)["project"], "leonaid")

    def test_backup_in_a_worktree_targets_the_worktree_project(self):
        with tempfile.TemporaryDirectory() as directory:
            main, worktree = self.make_repository(Path(directory))
            self.record_main(main)
            stub = Path(directory) / "bin"
            stub.mkdir()
            log = Path(directory) / "docker.log"
            # A Docker stand-in that records every call and reports nothing.
            (stub / "docker").write_text(
                f'#!/bin/sh\nprintf "%s " "$@" >>"{log}"\necho >>"{log}"\n'
            )
            (stub / "docker").chmod(0o755)
            (worktree / ".env.local").write_text("LEONAID_HTTP_PORT=28100\n")
            password = Path(directory) / "password"
            password.write_text("synthetic\n")
            self.run_cli(
                worktree,
                "backup",
                PATH=f"{stub}:{os.environ['PATH']}",
                LEONAID_BACKUP_REPOSITORY=str(Path(directory) / "repository"),
                LEONAID_BACKUP_PASSWORD_FILE=str(password),
            )
            project = self.instance(worktree)["project"]
            calls = log.read_text().splitlines()
            targeted = [
                call.split()[call.split().index("--project-name") + 1]
                for call in calls
                if "--project-name" in call.split()
            ]
            self.assertTrue(targeted, calls)
            self.assertEqual(set(targeted), {project})
            # Only the read-only owner probe may name the main project.
            self.assertFalse(
                [
                    call
                    for call in calls
                    if "com.docker.compose.project=leonaid " in call + " "
                    and not call.startswith("ps ")
                ]
            )

    def fake_docker(self, directory: Path, owners: str = "") -> str:
        """PATH with a Docker stand-in: `ps` reports `owners`, all else succeeds."""
        stub = directory / "fake-bin"
        stub.mkdir(exist_ok=True)
        (directory / "owners").write_text(owners)
        (stub / "docker").write_text(
            f'#!/bin/sh\n[ "$1" = ps ] && cat "{directory / "owners"}"\nexit 0\n'
        )
        (stub / "docker").chmod(0o755)
        return f"{stub}:{os.environ['PATH']}"

    def test_unrecorded_main_checkout_is_never_rewritten(self):
        with tempfile.TemporaryDirectory() as directory:
            main, worktree = self.make_repository(Path(directory))
            env_text = "LEONAID_HTTP_PORT=28080\nLEONAID_HTTPS_PORT=28081\n"
            (main / ".env.local").write_text(env_text)
            path = self.fake_docker(Path(directory))
            for command in (["bootstrap"], ["dev"]):
                result = self.run_cli(main, *command, PATH=path)
                self.assertNotEqual(result.returncode, 0, command)
                self.assertIn("--main-instance", result.stderr, command)
            self.assertEqual((main / ".env.local").read_text(), env_text)
            # Owning the running leonaid containers is just as conclusive.
            (main / ".env.local").write_text("LEONAID_HTTP_PORT=28090\n")
            path = self.fake_docker(Path(directory), f"{main}/infra/compose\n")
            result = self.run_cli(main, "bootstrap", PATH=path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("looks like the main development instance", result.stderr)
            # A worktree is never mistaken for it, nor recorded as it.
            (worktree / ".env.local").write_text(env_text)
            result = self.run_cli(worktree, "bootstrap", "--main-instance", PATH=path)
            self.assertIn("linked worktree cannot be the main", result.stderr)
            self.assertNotEqual(
                self.instance(worktree, LEONAID_MAIN_CHECKOUT=str(worktree))["project"],
                "leonaid",
            )

    def test_main_instance_refused_when_another_checkout_owns_it(self):
        with tempfile.TemporaryDirectory() as directory:
            main, _ = self.make_repository(Path(directory))
            path = self.fake_docker(
                Path(directory), "/elsewhere/leonaid/infra/compose\n"
            )
            result = self.run_cli(main, "bootstrap", "--main-instance", PATH=path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("belongs to /elsewhere/leonaid", result.stderr)
            self.assertFalse((main / ".local/main-instance").exists())

    def test_scripts_refuse_a_missing_project(self):
        source = Path(__file__).resolve().parents[1]
        for script in (
            "tools/backup/backup.sh",
            "infra/upgrade/maintenance.sh",
            "infra/upgrade/twenty-queue-store.sh",
        ):
            text = (source / script).read_text()
            self.assertIn("${LEONAID_COMPOSE_PROJECT:?", text, script)
            self.assertNotIn("LEONAID_COMPOSE_PROJECT:-", text, script)

    def test_env_stop_refuses_a_fixture_owner_naming_the_dev_project(self):
        # test-env-stop only follows owner.json; a tampered or stale owner that
        # names the main dev project must be refused before any Docker call.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            cache = root / ".local/test-stack"
            cache.mkdir(parents=True)
            for project in ("leonaid", "leonaid-wt-1"):
                (cache / "owner.json").write_text(
                    '{"schemaVersion": 1, "root": "%s", "project": "%s"}'
                    % (root.resolve(), project)
                )
                result = subprocess.run(
                    [
                        sys.executable,
                        "-c",
                        "from tools.testing.local_stack import LocalStack; from pathlib import Path; LocalStack(Path(__import__('sys').argv[1]), stop=True)",
                        str(root),
                    ],
                    cwd=Path(__file__).resolve().parents[1],
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("refusing Docker mutations", result.stderr)


class SharedPackageCacheTests(unittest.TestCase):
    def test_toolchain_containers_use_the_private_host_cache(self):
        source = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            checkout = base / "checkout"
            for name in ("leonaid", "tools/testing/phase.sh", "infra/locks/images.env"):
                (checkout / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(source / name, checkout / name)
            stub = base / "bin"
            stub.mkdir()
            log = base / "docker.log"
            # Records the arguments of each Docker call and reports success.
            (stub / "docker").write_text(
                f'#!/bin/sh\nfor a in "$@"; do echo "$a"; done >>"{log}"\n'
            )
            (stub / "docker").chmod(0o755)
            cache = base / "packages"
            result = subprocess.run(
                [str(checkout / "leonaid"), "test-unit"],
                env={
                    **os.environ,
                    "PATH": f"{stub}:{os.environ['PATH']}",
                    "LEONAID_PACKAGE_CACHE": str(cache),
                    "LEONAID_SKIP_DEPENDENCY_CHECK": "1",
                },
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            arguments = log.read_text().splitlines()
            self.assertIn(f"{cache}/uv:/cache/uv", arguments)
            self.assertIn("UV_CACHE_DIR=/cache/uv", arguments)
            self.assertIn("UV_LINK_MODE=clone", arguments)
            self.assertEqual((cache / "uv").stat().st_mode & 0o777, 0o700)
            self.assertEqual(cache.stat().st_mode & 0o777, 0o700)


class StaleDependencyTests(unittest.TestCase):
    """bootstrap stamps installs; commands and doctor compare the stamps."""

    def checkout(self, base: Path) -> tuple[Path, dict[str, str]]:
        source = Path(__file__).resolve().parents[1]
        checkout = base / "checkout"
        for name in (
            "leonaid",
            "tools/testing/phase.sh",
            "infra/locks/images.env",
            "uv.lock",
            "pyproject.toml",
            "bun.lock",
            "package.json",
            ".env.example",
        ):
            (checkout / name).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(source / name, checkout / name)
        (checkout / ".env.local").write_text(
            "LEONAID_HTTP_PORT=28190\nLEONAID_HTTPS_PORT=28191\n"
        )
        for executable in (".venv/bin/python", "node_modules/.bin/tsc"):
            (checkout / executable).parent.mkdir(parents=True)
            (checkout / executable).write_text("#!/bin/sh\n")
            (checkout / executable).chmod(0o755)
        stub = base / "bin"
        stub.mkdir()
        # Docker stand-in: every call succeeds and installs nothing.
        (stub / "docker").write_text("#!/bin/sh\nexit 0\n")
        (stub / "docker").chmod(0o755)
        environment = {
            **os.environ,
            "PATH": f"{stub}:{os.environ['PATH']}",
            "LEONAID_PACKAGE_CACHE": str(base / "packages"),
        }
        return checkout, environment

    def run_cli(self, checkout, environment, *args):
        return subprocess.run(
            [str(checkout / "leonaid"), *args],
            env=environment,
            capture_output=True,
            text=True,
        )

    def test_bootstrap_stamps_and_commands_follow_the_lockfiles(self):
        with tempfile.TemporaryDirectory() as directory:
            checkout, environment = self.checkout(Path(directory))
            # Unstamped (from before the guard): commands and doctor warn only.
            result = self.run_cli(checkout, environment, "test-unit")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(".venv has no lock stamp", result.stderr)
            result = self.run_cli(checkout, environment, "doctor")
            self.assertIn("doctor: WARNING: .venv has no lock stamp", result.stderr)
            self.assertNotIn("does not match uv.lock", result.stderr)

            self.run_cli(checkout, environment, "bootstrap")
            for stamp in (".venv", "node_modules"):
                self.assertTrue((checkout / stamp / ".leonaid-lock-stamp").is_file())
            for command in ("test-unit", "test-surveys-dependencies"):
                result = self.run_cli(checkout, environment, command)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "", command)

            # Scripts and tool config are no dependency change.
            with (checkout / "pyproject.toml").open("a") as manifest:
                manifest.write("\n[tool.example]\nsetting = 1\n")
            (checkout / "package.json").write_text(
                (checkout / "package.json")
                .read_text()
                .replace('"typecheck"', '"typecheck-renamed"')
            )
            self.assertEqual(
                self.run_cli(checkout, environment, "test-unit").stderr, ""
            )

            # A lockfile change refuses the toolchain that installs it.
            with (checkout / "bun.lock").open("a") as lock:
                lock.write("\n")
            result = self.run_cli(checkout, environment, "test-surveys-dependencies")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("node_modules is stale", result.stderr)
            self.assertEqual(
                self.run_cli(checkout, environment, "test-unit").returncode, 0
            )
            result = self.run_cli(checkout, environment, "doctor")
            self.assertIn("node_modules does not match bun.lock", result.stderr)

            # So does a new toolchain image pin.
            images = checkout / "infra/locks/images.env"
            images.write_text(
                images.read_text().replace("UV_IMAGE=", "UV_IMAGE=example.invalid/", 1)
            )
            result = self.run_cli(checkout, environment, "test-unit")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(".venv is stale", result.stderr)
            self.assertIn("./leonaid bootstrap", result.stderr)
            environment["LEONAID_SKIP_DEPENDENCY_CHECK"] = "1"
            self.assertEqual(
                self.run_cli(checkout, environment, "test-unit").returncode, 0
            )

    def test_missing_installs_only_warn(self):
        # Some commands need just the toolchain image, not .venv/node_modules.
        with tempfile.TemporaryDirectory() as directory:
            checkout, environment = self.checkout(Path(directory))
            shutil.rmtree(checkout / ".venv")
            result = self.run_cli(checkout, environment, "test-unit")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(".venv is missing", result.stderr)


if __name__ == "__main__":
    unittest.main()
