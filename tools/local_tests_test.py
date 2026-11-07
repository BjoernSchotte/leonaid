"""Local selection, cache invalidation and process ownership regressions."""

import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.testing.local_stack import fingerprints
from tools.surveys.gate import ci_shards, load_manifest


class LocalTests(unittest.TestCase):
    def test_default_groups_are_disjoint_and_exclude_recovery(self):
        root = Path(__file__).resolve().parents[1]
        cli = (root / "leonaid").read_text()
        integration = cli.split("  test-integration)\n")[1].split("    ;;")[0]
        e2e = cli.split("  test-e2e)\n")[1].split("    ;;")[0]
        import re

        groups = [
            set(re.findall(r"tools/[a-z_/]+\.sh", part)) for part in (integration, e2e)
        ]
        self.assertFalse(groups[0] & groups[1])
        for part in (integration, e2e):
            self.assertNotIn("backup", part)
            self.assertNotIn("upgrade", part)
        manifest = load_manifest(root)
        pr = {
            c
            for shard in ci_shards(manifest, "pr")
            for c in manifest["ciShards"][shard]
        }
        nightly = {
            c
            for shard in ci_shards(manifest, "nightly")
            for c in manifest["ciShards"][shard]
        }
        self.assertFalse(pr & nightly)
        self.assertEqual(len(pr), 26)  # passing/failing foundation proofs are separate
        self.assertEqual(len(nightly), 13)

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


if __name__ == "__main__":
    unittest.main()
