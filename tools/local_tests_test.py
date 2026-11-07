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
    """A linked worktree must never address the main checkout's dev instance."""

    def make_repository(self, directory: Path) -> tuple[Path, Path]:
        source = Path(__file__).resolve().parents[1]
        main = directory / "main"
        for name in ("leonaid", "tools/testing/phase.sh", "infra/locks/images.env"):
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

    def instance(self, checkout: Path, **env: str) -> dict[str, str]:
        result = subprocess.run(
            [str(checkout / "leonaid"), "local-instance"],
            capture_output=True,
            text=True,
            check=True,
            env={**os.environ, **env},
        )
        return dict(line.split("=", 1) for line in result.stdout.splitlines())

    def test_worktree_gets_its_own_project_and_never_main_ports(self):
        with tempfile.TemporaryDirectory() as directory:
            main, worktree = self.make_repository(Path(directory))
            primary = self.instance(main)
            linked = self.instance(worktree)
            self.assertEqual(primary["project"], "leonaid")
            self.assertEqual(primary["reserved_ports"], "")
            self.assertRegex(linked["project"], r"\Aleonaid-wt-[0-9]+\Z")
            self.assertEqual(linked["checkout"], "worktree")
            self.assertEqual(
                linked["reserved_ports"].split(), ["28080", "28081", "28090", "28091"]
            )
            # Deterministic per path; an explicit override still wins.
            self.assertEqual(self.instance(worktree)["project"], linked["project"])
            self.assertEqual(
                self.instance(worktree, LEONAID_COMPOSE_PROJECT="leonaid-x")["project"],
                "leonaid-x",
            )

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
