"""Content-hash image tags: every build input changes the tag, nothing else does.

Real files and, for the Compose mirror and tagging, the real Docker CLI.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["LEONAID_IMAGE_REPOSITORY"] = "leonaid-local-selftest"
import image_tags
from ci_fixture import environment

ROOT = Path(__file__).resolve().parents[2]
PINNED = "docker.io/library/alpine:3@sha256:" + "a" * 64
DOCKERFILE = f"""FROM {PINNED} AS build
WORKDIR /w
COPY package.json ./
COPY apps/web ./apps/web
COPY tools/*.mjs ./tools/
RUN --mount=type=cache,target=/root/.cache true
FROM {PINNED}
COPY --from=build /w /w
"""


class ContentHashTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.root)])
        files = {
            "Dockerfile": DOCKERFILE,
            ".dockerignore": "node_modules\n**/.astro\napps/*/dist\n",
            "package.json": "{}",
            "apps/web/src/main.ts": "export const a = 1;\n",
            "apps/web/dist/bundle.js": "built",
            "apps/web/.astro/types.d.ts": "generated",
            "tools/one.mjs": "1",
            "docs/readme.md": "not copied",
        }
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def tag(self):
        return image_tags.build_hash(self.root, ".", "Dockerfile")

    def assert_changes(self, change):
        before = self.tag()
        change()
        self.assertNotEqual(self.tag(), before)

    def assert_keeps(self, change):
        before = self.tag()
        change()
        self.assertEqual(self.tag(), before)

    def test_every_build_input_changes_the_tag(self):
        root = self.root
        self.assert_changes(lambda: (root / "apps/web/src/main.ts").write_text("2"))
        self.assert_changes(lambda: (root / "apps/web/src/new.ts").write_text("new"))
        self.assert_changes(lambda: (root / "package.json").write_text('{"a":1}'))
        self.assert_changes(lambda: (root / "tools/two.mjs").write_text("2"))
        self.assert_changes(lambda: (root / "apps/web/src/main.ts").chmod(0o755))
        self.assert_changes(
            lambda: (root / "Dockerfile").write_text(DOCKERFILE + "ENV X=1\n")
        )
        self.assert_changes(
            lambda: (root / ".dockerignore").write_text("node_modules\n")
        )

    def test_ignored_and_uncopied_files_keep_the_tag(self):
        root = self.root
        self.assert_keeps(lambda: (root / "docs/readme.md").write_text("changed"))
        self.assert_keeps(lambda: (root / "apps/web/dist/bundle.js").write_text("x"))
        self.assert_keeps(lambda: (root / "apps/web/.astro/types.d.ts").write_text("y"))
        self.assert_keeps(lambda: (root / "tools/note.txt").write_text("not *.mjs"))

    def test_incomplete_inputs_are_not_shared(self):
        for dockerfile in (
            "FROM alpine:3\nCOPY package.json ./\n",
            f"FROM {PINNED}\nADD https://example.invalid/x /x\n",
            f"FROM {PINNED}\nRUN --mount=type=bind,source=.,target=/s true\n",
            f"FROM {PINNED}\nARG V\nCOPY $V /x\n",
            f"FROM {PINNED}\nCOPY missing ./\n",
            f"FROM {PINNED}\nRUN <<EOF\ntrue\nEOF\n",
        ):
            (self.root / "Dockerfile").write_text(dockerfile)
            with self.assertRaises(image_tags.Unsupported, msg=dockerfile):
                self.tag()

    def test_copy_from_must_be_a_stage_or_pinned(self):
        for origin, shared in (
            ("build", True),
            ("0", True),
            (PINNED, True),
            ("node:22", False),
            ("ghcr.io/x/y:latest", False),
        ):
            (self.root / "Dockerfile").write_text(
                f"FROM {PINNED} AS build\nFROM {PINNED}\nCOPY --from={origin} /x /x\n"
            )
            if shared:
                self.tag()
            else:
                with self.assertRaises(image_tags.Unsupported, msg=origin):
                    self.tag()

    def test_symlinks_and_dockerignore_details(self):
        root = self.root
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(outside)])
        (root / "apps/web/src/leak").symlink_to(outside)
        with self.assertRaises(image_tags.Unsupported):
            self.tag()
        (root / "apps/web/src/leak").unlink()
        # [!...] is a negated class in Go's filepath.Match.
        (root / ".dockerignore").write_text("apps/web/src/[!m]*\n")
        before = self.tag()
        (root / "apps/web/src/other.ts").write_text("ignored")
        self.assertEqual(self.tag(), before)
        (root / "apps/web/src/main.ts").write_text("copied")
        self.assertNotEqual(self.tag(), before)
        (root / "Dockerfile.dockerignore").write_text("*\n")
        with self.assertRaises(image_tags.Unsupported):
            self.tag()

    def test_cli_prints_the_hash_or_refuses(self):
        script = ROOT / "tools/testing/image_tags.py"
        result = subprocess.run(
            [sys.executable, str(script), "api"], capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertRegex(result.stdout, r"\A[0-9a-f]{24}\n\Z")
        result = subprocess.run(
            [sys.executable, str(script), "unknown"], capture_output=True, text=True
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")


class ComposeMirrorTests(unittest.TestCase):
    def test_build_table_matches_compose(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / "env"
            env_file.write_text(environment(ROOT))
            config = subprocess.run(
                [
                    "docker",
                    "compose",
                    "--env-file",
                    str(env_file),
                    "--file",
                    str(ROOT / "infra/compose/compose.yml"),
                    "--profile",
                    "*",
                    "config",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=True,
            ).stdout
        builds = {
            name: service["build"]
            for name, service in json.loads(config)["services"].items()
            if "build" in service
        }
        self.assertEqual(set(builds), set(image_tags.BUILDS))
        for name, build in builds.items():
            # The CLI (BUILDS) and the harness (rendered config) hash alike.
            self.assertEqual(
                image_tags.normalize(ROOT, build),
                image_tags.normalize(ROOT, image_tags.BUILDS[name]),
                name,
            )
        self.assertEqual(
            image_tags.spec_hash(ROOT, builds["api"]),
            image_tags.content_hash(ROOT, "api"),
        )


class TaggingTests(unittest.TestCase):
    """adopt/record/prune with the real Docker CLI in a test-only repository."""

    project = "leonaid-imagetagtest"

    def setUp(self):
        self.alpine = next(
            line.split("=", 1)[1].strip("\"'")
            for line in (ROOT / "infra/locks/images.env").read_text().splitlines()
            if line.startswith("ALPINE_IMAGE=")
        )
        subprocess.run(
            ["docker", "pull", "-q", self.alpine], check=True, capture_output=True
        )
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.root)])
        (self.root / "ctx").mkdir()
        (self.root / "ctx/Dockerfile").write_text(
            f"FROM {PINNED}\nCOPY app.txt /app.txt\n"
        )
        (self.root / "ctx/app.txt").write_text("one")
        self.builds = {
            "svc": {"context": str(self.root / "ctx"), "dockerfile": "Dockerfile"}
        }
        self.state = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.state)])
        self.previous_state = image_tags.STATE
        image_tags.STATE = self.state
        self.addCleanup(setattr, image_tags, "STATE", self.previous_state)
        self.addCleanup(self.remove_tags)

    def remove_tags(self):
        listing = subprocess.run(
            [
                "docker",
                "image",
                "ls",
                f"{image_tags.REPOSITORY}/svc",
                "--format",
                "{{.Repository}}:{{.Tag}}",
            ],
            capture_output=True,
            text=True,
        ).stdout.split()
        subprocess.run(
            ["docker", "image", "rm", f"{self.project}-svc", *listing],
            capture_output=True,
        )

    def build(self):
        # Stands in for `compose build`: any image under the project tag.
        subprocess.run(
            ["docker", "tag", self.alpine, f"{self.project}-svc"], check=True
        )

    def test_build_is_recorded_and_then_adopted(self):
        missing = image_tags.adopt(self.root, self.project, self.builds, ["svc"])
        self.assertEqual(list(missing), ["svc"])
        self.build()
        self.assertEqual(
            image_tags.record(self.root, self.project, self.builds, missing), ["svc"]
        )
        shared = f"{image_tags.REPOSITORY}/svc:{missing['svc']}"
        self.assertTrue(image_tags.exists(shared))
        subprocess.run(["docker", "image", "rm", f"{self.project}-svc"], check=True)
        os.environ["LEONAID_IMAGE_MAX_AGE_DAYS"] = "100000"
        self.addCleanup(os.environ.pop, "LEONAID_IMAGE_MAX_AGE_DAYS", None)
        self.assertEqual(
            image_tags.adopt(self.root, self.project, self.builds, ["svc"]), {}
        )
        self.assertTrue(image_tags.exists(f"{self.project}-svc"))

    def test_inputs_changed_during_the_build_are_not_recorded(self):
        missing = image_tags.adopt(self.root, self.project, self.builds, ["svc"])
        self.build()
        (self.root / "ctx/app.txt").write_text("edited while building")
        self.assertEqual(
            image_tags.record(self.root, self.project, self.builds, missing), []
        )
        self.assertFalse(
            image_tags.exists(f"{image_tags.REPOSITORY}/svc:{missing['svc']}")
        )

    def test_old_or_vanished_images_are_rebuilt(self):
        missing = image_tags.adopt(self.root, self.project, self.builds, ["svc"])
        self.build()
        image_tags.record(self.root, self.project, self.builds, missing)
        subprocess.run(["docker", "image", "rm", f"{self.project}-svc"], check=True)
        # The stand-in image (alpine) is months old: beyond the default age.
        self.assertEqual(
            image_tags.adopt(self.root, self.project, self.builds, ["svc"]), missing
        )
        subprocess.run(
            ["docker", "image", "rm", f"{image_tags.REPOSITORY}/svc:{missing['svc']}"],
            check=True,
        )
        os.environ["LEONAID_IMAGE_MAX_AGE_DAYS"] = "100000"
        self.addCleanup(os.environ.pop, "LEONAID_IMAGE_MAX_AGE_DAYS", None)
        self.assertEqual(
            image_tags.adopt(self.root, self.project, self.builds, ["svc"]), missing
        )

    def test_overlay_build_sections_are_hashed(self):
        base = image_tags.spec_hash(self.root, self.builds["svc"])
        with_args = dict(self.builds["svc"], args={"BUN_IMAGE": "x"})
        self.assertNotEqual(image_tags.spec_hash(self.root, with_args), base)
        with_target = dict(self.builds["svc"], target="build")
        self.assertNotEqual(image_tags.spec_hash(self.root, with_target), base)
        for key in ("secrets", "ssh", "additional_contexts"):
            with self.assertRaises(image_tags.Unsupported):
                image_tags.spec_hash(self.root, dict(self.builds["svc"], **{key: {}}))
        config = {
            "services": {
                "svc": {"build": with_args},
                "named": {"build": self.builds["svc"], "image": "x/y:1"},
                "pulled": {"image": "x/z:1"},
            }
        }
        self.assertEqual(image_tags.effective_builds(config), {"svc": with_args})

    def test_prune_keeps_the_most_recently_used_tags(self):
        references = [f"{image_tags.REPOSITORY}/svc:t{n}" for n in range(3)]
        for index, reference in enumerate(references):
            subprocess.run(["docker", "tag", self.alpine, reference], check=True)
            marker = self.state / "svc" / f"t{index}"
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.touch()
            os.utime(marker, (1000 + index, 1000 + index))
        self.assertEqual(sorted(image_tags.prune("svc", keep=2)), ["t0"])
        self.assertFalse(image_tags.exists(references[0]))
        self.assertTrue(image_tags.exists(references[2]))
        self.assertTrue(image_tags.exists(self.alpine))


if __name__ == "__main__":
    unittest.main()
