"""Focused receipt boundaries before real restore/reapplication integration."""

import argparse
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
from uuid import uuid4
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "restore_state", Path(__file__).with_name("restore-state.py")
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = {
            "services": {
                "api": {
                    "environment": {
                        "LEONAID_SESSION_ENCRYPTION_KEY": "synthetic-recovery-key-" * 3
                    }
                }
            }
        }
        self.config_file = self.root / "config.json"
        self.config_file.write_text(json.dumps(self.config))
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text('{"fixture": true}')
        self.args = argparse.Namespace(
            action="prepare",
            state=str(self.root / "receipt.json"),
            config=str(self.config_file),
            source="leonaid-source",
            target="leonaid-restore-receipt",
            repository="s3:synthetic",
            expected_manifest=str(self.manifest),
            manifest=str(self.manifest),
        )
        self.volumes = {"volume": {"name": "synthetic", "createdAt": "one"}}
        self.addCleanup(patch.stopall)
        patch.object(module, "resources", lambda _: copy.deepcopy(self.volumes)).start()
        patch.dict(
            os.environ,
            {"LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH": "2026-09-07T12:00:00+00:00"},
        ).start()
        module.receipt(self.args)
        self.args.action = "check"

    def test_phase_sequence(self) -> None:
        module.receipt(self.args)
        self.args.action = "verified"
        module.receipt(self.args)
        self.args.action = "check"
        module.receipt(self.args)
        self.args.action = "starting"
        module.receipt(self.args)
        self.args.action = "check"
        with self.assertRaises(ValueError):
            module.receipt(self.args)
        self.args.action = "complete"
        module.receipt(self.args)
        self.args.action = "check"
        with self.assertRaises(ValueError):
            module.receipt(self.args)

    def test_changed_binding(self) -> None:
        for field in ("source", "target", "repository"):
            args = copy.copy(self.args)
            setattr(args, field, "changed")
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.receipt(args)

    def test_changed_config_or_key(self) -> None:
        for change in (
            {"extra": True},
            {
                "services": {
                    "api": {
                        "environment": {
                            "LEONAID_SESSION_ENCRYPTION_KEY": "different-key-" * 4
                        }
                    }
                }
            },
        ):
            self.config_file.write_text(json.dumps({**self.config, **change}))
            with self.assertRaises(ValueError):
                module.receipt(self.args)

    def test_manifest_changed(self) -> None:
        self.manifest.write_text('{"fixture": false}')
        with self.assertRaises(ValueError):
            module.receipt(self.args)

    def test_replaced_volume(self) -> None:
        self.volumes["volume"]["createdAt"] = "replacement"
        with self.assertRaises(ValueError):
            module.receipt(self.args)

    def test_application_container(self) -> None:
        with patch.object(
            module, "resources", side_effect=ValueError("application container")
        ):
            with self.assertRaises(ValueError):
                module.receipt(self.args)

    def test_tampering(self) -> None:
        p = Path(self.args.state)
        value = json.loads(p.read_text())
        value["payload"]["phase"] = "verified"
        p.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            module.receipt(self.args)

    def test_missing_and_symlink(self) -> None:
        p = Path(self.args.state)
        p.unlink()
        with self.assertRaises(OSError):
            module.receipt(self.args)
        p.symlink_to(self.manifest)
        with self.assertRaises(OSError):
            module.receipt(self.args)

    def test_permissions(self) -> None:
        os.chmod(self.args.state, 0o644)
        with self.assertRaises(ValueError):
            module.receipt(self.args)

    def test_cutoff_cannot_regress_or_disappear(self) -> None:
        for value in ("", "2026-09-07T11:59:59+00:00", "2026-09-07T12:00:00"):
            with patch.dict(
                os.environ, {"LEONAID_SURVEY_ERASURE_REQUIRED_THROUGH": value}
            ):
                with self.assertRaises(ValueError):
                    module.receipt(self.args)


class ResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = "leonaid-restore-resources"
        self.services = ["core-postgres", "twenty-postgres", "rustfs"]
        self.owner = self.target
        self.ids = "container-1"

    def docker(self, *args: str) -> str:
        if args[0] == "ps":
            self.assertIn("-aq", args)
            return self.ids
        if args[0] == "inspect":
            return json.dumps(
                [
                    {"Config": {"Labels": {"com.docker.compose.service": name}}}
                    for name in self.services
                ]
            )
        self.assertEqual(args[:2], ("volume", "inspect"))
        return json.dumps(
            [
                {
                    "Name": args[2],
                    "CreatedAt": "2026-09-07T12:00:00Z",
                    "Driver": "local",
                    "Labels": {"com.docker.compose.project": self.owner},
                }
            ]
        )

    def test_data_only_resources_are_bound(self) -> None:
        with patch.object(module, "docker", side_effect=self.docker):
            volumes = module.resources(self.target)
        self.assertEqual(
            set(volumes),
            {
                "core-postgres-data",
                "twenty-postgres-data",
                "rustfs-data",
                "twenty-server-data",
            },
        )
        self.assertTrue(
            all(v["name"].startswith(self.target + "_") for v in volumes.values())
        )

    def test_any_application_container_blocks_including_stopped(self) -> None:
        for name in ("api", "public", "worker", "survey-validator", "proxy", "unknown"):
            with self.subTest(service=name):
                self.services = ["core-postgres", name]
                with patch.object(module, "docker", side_effect=self.docker):
                    with self.assertRaises(ValueError):
                        module.resources(self.target)

    def test_missing_containers_and_foreign_volumes_block(self) -> None:
        with patch.object(module, "docker", side_effect=self.docker):
            self.ids = ""
            with self.assertRaises(ValueError):
                module.resources(self.target)
            self.ids = "container-1"
            self.owner = "another-project"
            with self.assertRaises(ValueError):
                module.resources(self.target)


class LockTests(unittest.TestCase):
    def test_same_target_is_exclusive(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "ready"
            target = "leonaid-restore-lock-" + uuid4().hex[:16]
            command = [
                sys.executable,
                str(Path(__file__).with_name("restore-state.py")),
                "locked",
                "--target",
                target,
                "--",
            ]
            process = subprocess.Popen(
                command
                + [
                    sys.executable,
                    "-c",
                    "import pathlib,sys;pathlib.Path(sys.argv[1]).write_text('ready');sys.stdin.read()",
                    str(marker),
                ],
                stdin=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 5
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(marker.exists())
                blocked = subprocess.run(
                    command + [sys.executable, "-c", "pass"],
                    capture_output=True,
                    timeout=5,
                )
                self.assertEqual(blocked.returncode, 1)
            finally:
                process.communicate(timeout=5)
                (Path(tempfile.gettempdir()) / (target + ".restore.lock")).unlink(
                    missing_ok=True
                )
            self.assertEqual(process.returncode, 0)


if __name__ == "__main__":
    unittest.main()
