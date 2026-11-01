#!/usr/bin/env python3
"""Prove the CalVer release helpers and release.sh guards with real Git repos."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1]))

from tools.release.release_assets import (  # noqa: E402
    ReleaseAssetError,
    image_environment,
    render_environment,
)

LIB = HERE / "release-lib.sh"
SCRIPT = HERE / "release.sh"
COMMIT = "a" * 40
TARGETS = ("core", "web", "pwa", "public", "proxy", "survey-validator")


def git(repository: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class Repository:
    """A throwaway repository with a bare origin, like a real checkout."""

    def __init__(self, root: Path) -> None:
        self.origin = root / "origin.git"
        self.path = root / "work"
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(self.origin)],
            check=True,
        )
        subprocess.run(
            ["git", "clone", "-q", str(self.origin), str(self.path)],
            check=True,
            capture_output=True,
        )
        git(self.path, "config", "user.email", "release-test@leonaid.invalid")
        git(self.path, "config", "user.name", "Release Test")
        git(self.path, "config", "tag.gpgSign", "false")
        git(self.path, "config", "commit.gpgSign", "false")
        git(self.path, "symbolic-ref", "HEAD", "refs/heads/main")

    def commit(self, message: str) -> str:
        git(self.path, "commit", "-q", "--allow-empty", "-m", message)
        return git(self.path, "rev-parse", "HEAD")

    def tag(self, name: str, ref: str = "HEAD") -> None:
        git(self.path, "tag", "-a", name, "-m", name, ref)

    def push(self) -> None:
        git(self.path, "push", "-q", "origin", "HEAD", "--tags")

    def lib(self, expression: str, month: str = "2026.11") -> str:
        result = subprocess.run(
            ["sh", "-c", f'. "{LIB}"; {expression}'],
            cwd=self.path,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, "RELEASE_MONTH": month},
        )
        return result.stdout.strip()

    def release(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["sh", str(SCRIPT), *arguments],
            cwd=self.path,
            capture_output=True,
            text=True,
            env={**os.environ, "RELEASE_MONTH": "2026.11"},
        )


class ReleaseLibraryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.directory.name))
        self.repository.commit("chore: start")

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_first_release_of_a_month_is_one(self) -> None:
        self.assertEqual(self.repository.lib("next_version"), "2026.11.1")

    def test_next_release_counts_numerically_and_ignores_other_months(self) -> None:
        for tag in ("v2026.10.7", "v2026.11.1", "v2026.11.9", "v2026.11.10"):
            self.repository.tag(tag)
        self.assertEqual(self.repository.lib("next_version"), "2026.11.11")
        self.assertEqual(self.repository.lib("next_version 2026.10"), "2026.10.8")

    def test_gaps_are_not_refilled(self) -> None:
        self.repository.tag("v2026.11.3")
        self.assertEqual(self.repository.lib("next_version"), "2026.11.4")

    def test_month_has_no_leading_zero(self) -> None:
        month = subprocess.run(
            ["sh", "-c", f'. "{LIB}"; RELEASE_MONTH= release_month'],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        year, number = month.split(".")
        self.assertEqual(len(year), 4)
        self.assertFalse(number.startswith("0"))

    def test_fix_releases_count_on_top_of_their_release(self) -> None:
        self.repository.tag("v2026.11.1")
        self.assertEqual(self.repository.lib("next_fix 2026.11.1"), "2026.11.1.1")
        self.repository.tag("v2026.11.1.1")
        self.repository.tag("v2026.11.1.2")
        self.repository.tag("v2026.11.10.5")
        self.assertEqual(self.repository.lib("next_fix 2026.11.1"), "2026.11.1.3")

    def test_last_tag_sorts_by_version_and_only_merged_tags(self) -> None:
        first = self.repository.commit("feat: one")
        self.repository.tag("v2026.11.2", first)
        self.repository.tag("v2026.11.10", first)
        self.repository.tag("not-a-release", first)
        git(self.repository.path, "checkout", "-q", "-b", "side")
        self.repository.commit("feat: side")
        self.repository.tag("v2026.12.1")
        git(self.repository.path, "checkout", "-q", "main")
        self.assertEqual(self.repository.lib("last_tag HEAD"), "v2026.11.10")

    def test_notes_group_conventional_commits(self) -> None:
        start = git(self.repository.path, "rev-parse", "HEAD")
        self.repository.commit("feat(worker): loop health")
        self.repository.commit("fix: static fallback")
        self.repository.commit("security: drop authlib")
        self.repository.commit("feat!: new env format")
        self.repository.commit("docs: runbook")
        self.repository.commit("chore(release): ignored")
        self.repository.commit("plain message")
        notes = self.repository.lib(f"release_notes {start} HEAD")
        sections = [line for line in notes.splitlines() if line.startswith("### ")]
        self.assertEqual(
            sections,
            [
                "### Breaking changes",
                "### Features",
                "### Fixes",
                "### Security",
                "### Other",
            ],
        )
        self.assertIn("- **worker:** loop health (", notes)
        self.assertIn("- docs: runbook (", notes)
        self.assertIn("- plain message (", notes)
        self.assertNotIn("ignored", notes)


class ReleaseScriptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.repository = Repository(Path(self.directory.name))
        self.repository.commit("feat: first feature")
        self.repository.push()

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_dry_run_on_main_shows_next_version_and_notes(self) -> None:
        self.repository.tag("v2026.11.1")
        self.repository.commit("fix: second")
        self.repository.push()
        result = self.repository.release("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LeonAid 2026.11.2 (since v2026.11.1)", result.stdout)
        self.assertIn("### Fixes", result.stdout)
        self.assertNotIn("first feature", result.stdout)

    def test_refuses_dirty_tree(self) -> None:
        (self.repository.path / "untracked.txt").write_text("x", encoding="utf-8")
        result = self.repository.release("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uncommitted changes", result.stderr)

    def test_refuses_unpushed_head(self) -> None:
        self.repository.commit("feat: local only")
        result = self.repository.release("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("HEAD is not origin/main", result.stderr)

    def test_refuses_other_branches(self) -> None:
        git(self.repository.path, "checkout", "-q", "-b", "feature/x")
        git(self.repository.path, "push", "-q", "-u", "origin", "feature/x")
        result = self.repository.release("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("releases come from main or release/YYYY.M.N", result.stderr)

    def test_fix_release_branch_numbers_on_top_of_its_base(self) -> None:
        self.repository.tag("v2026.11.1")
        git(self.repository.path, "checkout", "-q", "-b", "release/2026.11.1")
        self.repository.commit("fix: backported")
        git(
            self.repository.path,
            "push",
            "-q",
            "-u",
            "origin",
            "release/2026.11.1",
            "--tags",
        )
        result = self.repository.release("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("LeonAid 2026.11.1.1 (since v2026.11.1)", result.stdout)

    def test_fresh_release_branch_has_nothing_to_release(self) -> None:
        self.repository.tag("v2026.11.1")
        git(self.repository.path, "checkout", "-q", "-b", "release/2026.11.1")
        git(
            self.repository.path,
            "push",
            "-q",
            "-u",
            "origin",
            "release/2026.11.1",
            "--tags",
        )
        result = self.repository.release("--dry-run")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("nothing to release", result.stderr)

    def test_tagged_head_resumes_instead_of_tagging_again(self) -> None:
        self.repository.tag("v2026.11.1")
        self.repository.push()
        result = self.repository.release("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("2026.11.1 is tagged already: resuming", result.stdout)


class ReleaseAssetsTest(unittest.TestCase):
    def metadata(self) -> dict[str, object]:
        return {
            target: {"containerimage.digest": "sha256:" + "b" * 64}
            for target in TARGETS
        }

    def test_pins_every_image_with_tag_and_digest(self) -> None:
        environment = image_environment(
            self.metadata(),
            registry="ghcr.io/bjoernschotte/leonaid",
            version="2026.11.1",
            commit=COMMIT,
        )
        self.assertEqual(environment["LEONAID_SERVICE_VERSION"], "2026.11.1")
        self.assertEqual(
            environment["LEONAID_SURVEY_VALIDATOR_IMAGE"],
            "ghcr.io/bjoernschotte/leonaid/survey-validator:2026.11.1@sha256:"
            + "b" * 64,
        )

    def test_rejects_incomplete_or_malformed_input(self) -> None:
        incomplete = self.metadata()
        del incomplete["proxy"]
        bad_digest = self.metadata()
        bad_digest["web"] = {"containerimage.digest": "sha256:short"}
        cases = [
            (incomplete, "2026.11.1", COMMIT, "lacks targets: proxy"),
            (bad_digest, "2026.11.1", COMMIT, "web: missing or invalid"),
            (self.metadata(), "v2026.11.1", COMMIT, "not CalVer"),
            (self.metadata(), "2026.13.1", COMMIT, "not CalVer"),
            (self.metadata(), "2026.11.1", "abc", "40-character"),
        ]
        for metadata, version, commit, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ReleaseAssetError, message):
                    image_environment(
                        metadata,
                        registry="ghcr.io/bjoernschotte/leonaid",
                        version=version,
                        commit=commit,
                    )

    def test_render_replaces_each_key_once_and_requires_all(self) -> None:
        template = "# comment\nA=old\nB=keep\n"
        self.assertEqual(
            render_environment(template, {"A": "new"}),
            "# comment\nA=new\nB=keep\n",
        )
        with self.assertRaisesRegex(ReleaseAssetError, "lacks keys: C"):
            render_environment(template, {"C": "x"})
        with self.assertRaisesRegex(ReleaseAssetError, "appears twice"):
            render_environment("A=1\nA=2\n", {"A": "x"})


if __name__ == "__main__":
    unittest.main(verbosity=1)
