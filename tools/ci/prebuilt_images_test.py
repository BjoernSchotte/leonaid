#!/usr/bin/env python3
"""Self-tests of tools/ci/prebuilt_images.py (python3 -I, no network, no Docker)."""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import prebuilt_images as pi  # noqa: E402
from tools.testing import image_tags  # noqa: E402

HASH = "a" * 24


class Result:
    def __init__(self, code: int = 0, stdout: str = "") -> None:
        self.returncode, self.stdout, self.stderr = code, stdout, ""


class FakeDocker:
    """Answers pull, label inspect, tag, manifest inspect and push."""

    def __init__(self, present: set[str], label: str = HASH, push: int = 0) -> None:
        self.present, self.label, self.push_code = present, label, push
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *arguments: str, timeout: int = 0) -> Result:
        self.calls.append(arguments)
        service = arguments[-1].rsplit("/", 1)[-1].split(":")[0]
        if arguments[0] in ("pull", "manifest"):
            return Result(0 if service in self.present else 1)
        if arguments[:2] == ("image", "inspect"):
            return Result(stdout=self.label + "\n")
        if arguments[0] == "push":
            return Result(self.push_code)
        return Result()


class BakeTests(unittest.TestCase):
    def test_groups_expand_to_the_targets_of_the_real_bake_file(self) -> None:
        self.assertEqual(
            pi.expand(["build"]),
            [
                "api", "worker", "proxy", "web", "pwa", "public",
                "survey-validator", "campaign-site",
            ],
        )  # fmt: skip
        self.assertEqual(pi.expand(["api, proxy"]), ["api", "proxy"])
        with self.assertRaises(ValueError):
            pi.expand(["api,nope"])

    def test_bake_builds_what_the_hash_describes(self) -> None:
        """main publishes bake output under the Compose build's hash."""
        text = pi.BAKE_FILE.read_text(encoding="utf-8")
        found = re.findall(r'(?ms)^target "([a-z0-9-]+)" \{\n(.*?)^\}', text)
        self.assertEqual({name for name, _ in found}, set(image_tags.BUILDS))
        for name, body in found:
            with self.subTest(target=name):
                spec = dict(
                    re.findall(r'(?m)^  (context|dockerfile) = "([^"]+)"$', body)
                )
                self.assertEqual(spec, image_tags.BUILDS[name])
                self.assertNotRegex(body, r"(?m)^  (args|target|secret|ssh) =")


class PullTests(unittest.TestCase):
    def test_hits_are_tagged_and_misses_are_built(self) -> None:
        docker = FakeDocker({"api", "web"})
        misses, report = pi.pull(["api,web,proxy"], lambda s: HASH, docker)
        self.assertEqual(misses, ["proxy"])
        remote, local = f"{pi.REPOSITORY}/api:{HASH}", f"leonaid-local/api:{HASH}"
        self.assertIn(("tag", remote, local), docker.calls)
        self.assertTrue(report[0].startswith("hit  "))
        self.assertTrue(report[2].startswith("miss proxy"))

    def test_an_image_with_another_hash_is_removed_and_built(self) -> None:
        docker = FakeDocker({"api"}, label="b" * 24)
        misses, _ = pi.pull(["api"], lambda s: HASH, docker)
        self.assertEqual(misses, ["api"])
        self.assertIn(("image", "rm", f"{pi.REPOSITORY}/api:{HASH}"), docker.calls)
        self.assertFalse(any(call[0] == "tag" for call in docker.calls))

    def test_any_error_is_a_miss(self) -> None:
        def hasher(service: str) -> str:
            raise image_tags.Unsupported("FROM without digest")

        def broken(*arguments: str, timeout: int = 0) -> Result:
            raise subprocess.TimeoutExpired("docker", timeout)

        self.assertEqual(pi.pull(["api"], hasher, FakeDocker({"api"}))[0], ["api"])
        self.assertEqual(pi.pull(["api"], lambda s: HASH, broken)[0], ["api"])

    def test_outputs_are_single_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out"
            pi.output({"GITHUB_OUTPUT": str(path)}, bake="api,web")
            self.assertEqual(path.read_text(), "bake=api,web\n")
            with self.assertRaises(ValueError):
                pi.output({"GITHUB_OUTPUT": str(path)}, bake="api\nx=1")


class PublishTests(unittest.TestCase):
    def test_plan_lists_missing_tags_or_all(self) -> None:
        docker = FakeDocker({"api"})
        override = pi.plan(["api,web"], "c" * 40, hasher=lambda s: HASH, run=docker)
        self.assertEqual(
            override["target"],
            {
                "web": {
                    "tags": [f"{pi.REPOSITORY}/web:{HASH}"],
                    "labels": {
                        pi.HASH_LABEL: HASH,
                        "org.opencontainers.image.revision": "c" * 40,
                        "org.opencontainers.image.source": pi.SOURCE,
                    },
                }
            },
        )
        everything = pi.plan(["api,web"], "c" * 40, True, lambda s: HASH, docker)
        self.assertEqual(sorted(everything["target"]), ["api", "web"])

    def test_unclean_images_are_never_pushed(self) -> None:
        docker = FakeDocker(set())

        def cleaner(reference: str) -> list[str]:
            return ["forbidden file app/.env"] if reference == "x:1" else []

        failures = pi.publish(["x:1", "y:1"], docker, cleaner)
        self.assertEqual(failures, ["x:1: forbidden file app/.env"])
        pushes = [call for call in docker.calls if call[0] == "push"]
        self.assertEqual(pushes, [("push", "--quiet", "y:1")])

    def test_failed_push_fails(self) -> None:
        failures = pi.publish(["y:1"], FakeDocker(set(), push=1), lambda ref: [])
        self.assertEqual(failures, ["y:1: push failed"])


class SecretTests(unittest.TestCase):
    def test_forbidden_files(self) -> None:
        names = [
            "app/.env", "./app/.env.local", "app/.env.example", "srv/sessions.env",
            "root/.ssh/id_ed25519", "root/.docker/config.json", "app/.git/config",
            "app/src/env.py", "app/.environment",
        ]  # fmt: skip
        expected = [
            "app/.env", "app/.env.local", "app/.git/config",
            "root/.docker/config.json", "root/.ssh/id_ed25519", "srv/sessions.env",
        ]  # fmt: skip
        self.assertEqual(pi.forbidden(names), expected)

    def test_check_clean_reads_the_export_and_trivy(self) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for name in ("app/main.py", "app/.env"):
                archive.addfile(tarfile.TarInfo(name), io.BytesIO(b""))
        secret = {"RuleID": "github-pat"}
        report = {"Results": [{"Target": "/app/k", "Secrets": [secret]}]}

        def run(*arguments: str, timeout: int = 0) -> Result:
            if arguments[0] == "create":
                return Result(stdout="cid\n")
            if arguments[0] == "run":
                return Result(stdout=json.dumps(report))
            return Result()

        class Export:
            def __init__(self, command: list[str], stdout: Any) -> None:
                self.stdout, self.returncode = io.BytesIO(buffer.getvalue()), 0

            def __enter__(self) -> Export:
                return self

            def __exit__(self, *details: object) -> None:
                return None

        with mock.patch("subprocess.Popen", Export):
            problems = pi.check_clean("img:1", run)
        expected = ["forbidden file app/.env", "secret github-pat in /app/k"]
        self.assertEqual(problems, expected)


class CommandLineTests(unittest.TestCase):
    def test_runs_isolated_from_another_directory(self) -> None:
        script = Path(__file__).resolve().parent / "prebuilt_images.py"
        result = subprocess.run(
            [sys.executable, "-I", str(script), "--help"],
            capture_output=True,
            text=True,
            cwd=tempfile.gettempdir(),
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("publish", result.stdout)


if __name__ == "__main__":
    unittest.main()
