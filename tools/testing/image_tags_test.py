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
            context, dockerfile = image_tags.BUILDS[name]
            self.assertEqual(Path(build["context"]), (ROOT / context).resolve(), name)
            self.assertEqual(build.get("dockerfile", "Dockerfile"), dockerfile, name)
            self.assertFalse(
                set(build) - {"context", "dockerfile"},
                f"{name}: build args/targets must be hashed too",
            )


class TaggingTests(unittest.TestCase):
    def test_adopt_record_and_prune_only_touch_their_repository(self):
        project = "leonaid-imagetagtest"
        alpine = next(
            line.split("=", 1)[1].strip("\"'")
            for line in (ROOT / "infra/locks/images.env").read_text().splitlines()
            if line.startswith("ALPINE_IMAGE=")
        )
        subprocess.run(
            ["docker", "pull", "-q", alpine], check=True, capture_output=True
        )
        shared = image_tags.tag(ROOT, "proxy")
        self.addCleanup(
            subprocess.run,
            ["docker", "image", "rm", f"{project}-proxy", shared],
            capture_output=True,
        )
        self.assertEqual(image_tags.adopt(ROOT, project, ["proxy"]), ["proxy"])
        subprocess.run(["docker", "tag", alpine, f"{project}-proxy"], check=True)
        image_tags.record(ROOT, project, ["proxy"])
        self.assertTrue(image_tags.exists(shared))
        subprocess.run(["docker", "image", "rm", f"{project}-proxy"], check=True)
        self.assertEqual(image_tags.adopt(ROOT, project, ["proxy"]), [])
        self.assertTrue(image_tags.exists(f"{project}-proxy"))
        # Pruning keeps the newest tags and never another repository.
        old = f"{image_tags.REPOSITORY}/proxy:old"
        subprocess.run(["docker", "tag", alpine, old], check=True)
        self.addCleanup(
            subprocess.run, ["docker", "image", "rm", old], capture_output=True
        )
        image_tags.prune("proxy", keep=10)
        self.assertTrue(image_tags.exists(old))
        image_tags.prune("proxy", keep=1)
        self.assertEqual(
            [image_tags.exists(old), image_tags.exists(shared)].count(True), 1
        )
        self.assertTrue(image_tags.exists(alpine))
        self.assertTrue(image_tags.exists(f"{project}-proxy"))


if __name__ == "__main__":
    unittest.main()
