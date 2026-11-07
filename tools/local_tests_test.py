"""Local selection, cache invalidation and process ownership regressions."""

import fcntl
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.testing.local_stack import LocalStack, fingerprints
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


if __name__ == "__main__":
    unittest.main()
