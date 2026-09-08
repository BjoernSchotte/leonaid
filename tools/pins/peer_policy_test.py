"""Exercise peer-policy boundaries against minimal real manifest fixtures."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tools.pins.check import Problems, check_frontend


class PeerPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write(
            "package.json",
            {
                "packageManager": "bun@1.2.19",
                "engines": {"bun": "1.2.19", "node": "22.23.0"},
            },
        )
        self.write("bun.lock", {"lockfileVersion": 1})
        self.package: dict[str, Any] = {
            "name": "@leonaid/surveys",
            "peerDependencies": {"react": "^19.2.8", "react-dom": "^19.2.8"},
        }
        self.host: dict[str, Any] = {
            "dependencies": {
                "@leonaid/surveys": "workspace:*",
                "react": "19.2.8",
                "react-dom": "19.2.8",
            }
        }

    def write(self, relative: str, value: object) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def check(self) -> list[str]:
        self.write("packages/surveys/package.json", self.package)
        self.write("apps/host/package.json", self.host)
        problems = Problems()
        check_frontend(self.root, problems)
        return problems.items

    def test_reviewed_peers_with_exact_host_pass(self) -> None:
        self.assertEqual(self.check(), [])

    def test_wider_or_different_peer_ranges_fail(self) -> None:
        for version in ("*", ">=19", "^18.0.0", "^19.2.9", "~19.2.8"):
            with self.subTest(version=version):
                self.package["peerDependencies"]["react"] = version
                self.assertTrue(any("not exactly pinned" in x for x in self.check()))

    def test_exception_does_not_apply_to_other_dependencies(self) -> None:
        self.package["peerDependencies"]["survey-core"] = "^3.0.3"
        self.assertTrue(
            any("survey-core is not exactly pinned" in x for x in self.check())
        )

    def test_exception_does_not_apply_to_other_sections(self) -> None:
        for section in ("dependencies", "devDependencies", "optionalDependencies"):
            with self.subTest(section=section):
                self.write(
                    "packages/other/package.json", {section: {"react": "^19.2.8"}}
                )
                self.package[section] = {"react": "^19.2.8"}
                self.assertTrue(
                    any(
                        f"{section} dependency react is not exactly pinned" in x
                        for x in self.check()
                    )
                )
                del self.package[section]

    def test_exception_requires_both_path_and_package_identity(self) -> None:
        self.write("packages/other/package.json", self.package)
        self.assertTrue(
            any(
                "packages/other/package.json: peerDependencies" in x
                for x in self.check()
            )
        )
        self.package["name"] = "@other/surveys"
        self.assertTrue(
            any(
                "packages/surveys/package.json: peerDependencies" in x
                for x in self.check()
            )
        )

    def test_missing_ranged_or_unproven_host_runtime_fails(self) -> None:
        for name in ("react", "react-dom"):
            for version in (None, "^19.2.8", "19.2.9", "18.3.1", "workspace:*"):
                with self.subTest(name=name, version=version):
                    self.host["dependencies"][name] = version
                    self.assertTrue(
                        any(f"survey host must pin {name}" in x for x in self.check())
                    )
            self.host["dependencies"][name] = "19.2.8"


if __name__ == "__main__":
    unittest.main()
