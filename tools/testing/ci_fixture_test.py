"""Exercise the fixture boundary with real files and archives; no Docker required."""

import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

from ci_fixture import environment, key, validate

ROOT = Path(__file__).resolve().parents[2]


class FixtureBoundaryTests(unittest.TestCase):
    def payload(self, directory, *, link=False):
        state = directory / "state"
        state.write_text("synthetic database fixture")
        if link:
            state.unlink()
            state.symlink_to("/etc/passwd")
        archive = directory / "volume-0.tar"
        with tarfile.open(archive, "w") as output:
            output.add(state, arcname="state")
        metadata = {
            "version": 1,
            "key": key(ROOT),
            "syntheticOnly": True,
            "integrationKey": "",
            "volumes": ["core-postgres-data"],
            "files": {"volume-0.tar": hashlib.sha256(archive.read_bytes()).hexdigest()},
        }
        (directory / "manifest.json").write_text(json.dumps(metadata))
        return archive, metadata

    def test_regular_archive_passes_and_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            archive, _ = self.payload(directory)
            validate(ROOT, directory)
            with archive.open("ab") as output:
                output.write(b"changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                validate(ROOT, directory)

    def test_archive_cannot_link_to_host_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            self.payload(directory, link=True)
            with self.assertRaisesRegex(ValueError, "links or devices"):
                validate(ROOT, directory)

    def test_changed_inputs_and_non_synthetic_payload_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            _, metadata = self.payload(directory)
            metadata["syntheticOnly"] = False
            (directory / "manifest.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "provenance"):
                validate(ROOT, directory)
            metadata["key"] = "another-schema"
            (directory / "manifest.json").write_text(json.dumps(metadata))
            with self.assertRaisesRegex(ValueError, "inputs changed"):
                validate(ROOT, directory)

    def test_schema_changes_invalidate_but_request_handlers_do_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            migration = root / "migrations/example.py"
            handler = root / "src/leonaid/interfaces/api/example.py"
            for path in (migration, handler):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("initial")
            original = key(root)
            handler.write_text("changed request handler")
            self.assertEqual(key(root), original)
            migration.write_text("changed schema")
            self.assertNotEqual(key(root), original)

    def test_environment_is_deterministic_and_local(self):
        content = environment(ROOT)
        self.assertEqual(content, environment(ROOT))
        self.assertIn("LEONAID_ENV=local\n", content)
        self.assertIn("ci-fixture@leonaid.invalid", content)
        self.assertNotIn("__GENERATE_", content)


if __name__ == "__main__":
    unittest.main()
