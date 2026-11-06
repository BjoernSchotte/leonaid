"""Exercise registry verification and re-pinning with a recorded fake registry."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from tools.pins import image_digests as digests

ROOT = Path(__file__).resolve().parents[2]


def digest(character: str) -> str:
    # Built at runtime: this file carries no pinned reference for check.py.
    return "sha256:" + character * 64


OLD = digest("a")
NEW = digest("b")
OTHER = digest("c")
POSTGRES = "docker.io/library/postgres:16.15-alpine3.24"
CADDY = "docker.io/library/caddy:2.11.7-alpine"


class FakeRegistry:
    """Tag and digest lookups as docker buildx imagetools would answer them."""

    def __init__(self, tags: dict[str, str], digests_present: set[str]) -> None:
        self.tags = tags
        self.present = digests_present
        self.lookups: list[str] = []

    def __call__(self, reference: str) -> str:
        self.lookups.append(reference)
        if "@" in reference:
            found = reference.split("@", 1)[1]
            if found not in self.present:
                raise digests.NotFound(reference)
            return found
        if reference not in self.tags:
            raise digests.NotFound(reference)
        return self.tags[reference]


def pins(**images: str) -> dict[str, digests.Pin]:
    return {key: digests.parse_pin(key, image) for key, image in images.items()}


class GeneratorTest(unittest.TestCase):
    def test_committed_images_env_is_the_generated_one(self) -> None:
        lock = json.loads((ROOT / digests.LOCK).read_text(encoding="utf-8"))
        self.assertEqual(
            (ROOT / digests.ENV).read_text(encoding="utf-8"), digests.render_env(lock)
        )

    def test_env_rejects_foreign_lines(self) -> None:
        with self.assertRaisesRegex(digests.PinError, "unexpected line"):
            digests.parse_env("PATH=/usr/bin\n")
        with self.assertRaisesRegex(digests.PinError, "no images"):
            digests.parse_env("# empty\n")


class VerifyTest(unittest.TestCase):
    def setUp(self) -> None:
        # Upstream rebuilt postgres: the tag moved, the old digest still exists.
        self.registry = FakeRegistry({POSTGRES: NEW, CADDY: OTHER}, {OLD, NEW, OTHER})
        self.current = pins(
            POSTGRES_IMAGE=f"{POSTGRES}@{OLD}", CADDY_IMAGE=f"{CADDY}@{OTHER}"
        )

    def test_moved_tag_with_existing_digest_passes(self) -> None:
        problems, _ = digests.verify(self.current, self.registry, base=self.current)
        self.assertEqual(problems, [])
        self.assertNotIn(POSTGRES, self.registry.lookups)

    def test_all_tags_reports_the_drift(self) -> None:
        problems, _ = digests.verify(self.current, self.registry, all_tags=True)
        self.assertEqual(len(problems), 1)
        self.assertIn("POSTGRES_IMAGE", problems[0])
        self.assertIn("repin-images --image postgres", problems[0])

    def test_vanished_digest_fails(self) -> None:
        self.registry.present.discard(OLD)
        problems, _ = digests.verify(self.current, self.registry)
        self.assertEqual(len(problems), 1)
        self.assertIn("no longer in the registry", problems[0])

    def test_changed_pin_must_match_the_tag_now(self) -> None:
        base = pins(
            POSTGRES_IMAGE=f"{POSTGRES}@{OTHER}", CADDY_IMAGE=f"{CADDY}@{OTHER}"
        )
        problems, notes = digests.verify(self.current, self.registry, base=base)
        self.assertEqual(len(problems), 1)
        self.assertIn("this change pins", problems[0])
        self.assertIn("POSTGRES_IMAGE", notes[0])

    def test_changed_pin_on_the_current_digest_passes(self) -> None:
        head = pins(POSTGRES_IMAGE=f"{POSTGRES}@{NEW}", CADDY_IMAGE=f"{CADDY}@{OTHER}")
        problems, _ = digests.verify(head, self.registry, base=self.current)
        self.assertEqual(problems, [])

    def test_new_pin_is_checked_strictly(self) -> None:
        base = pins(CADDY_IMAGE=f"{CADDY}@{OTHER}")
        problems, _ = digests.verify(self.current, self.registry, base=base)
        self.assertEqual(len(problems), 1)
        self.assertIn("POSTGRES_IMAGE", problems[0])

    def test_changed_pin_with_unknown_tag_fails(self) -> None:
        del self.registry.tags[POSTGRES]
        base = pins(CADDY_IMAGE=f"{CADDY}@{OTHER}")
        problems, _ = digests.verify(self.current, self.registry, base=base)
        self.assertEqual(
            problems, [f"POSTGRES_IMAGE: tag {POSTGRES} is not in the registry"]
        )


class RepinTest(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.lock = {
            "schemaVersion": 1,
            "systems": [
                {"id": "postgres", "image": f"{POSTGRES}@{OLD}", "digest": OLD},
                {"id": "caddy", "image": f"{CADDY}@{OTHER}", "digest": OTHER},
            ],
        }
        self.write(digests.LOCK, json.dumps(self.lock, indent=2) + "\n")
        self.write(digests.ENV, digests.render_env(self.lock))
        self.write(
            Path("infra/compose/compose.yml"),
            f"services:\n  db:\n    image: postgres:16.15-alpine3.24@{OLD}\n",
        )
        self.write(Path("README.md"), f"docker run {POSTGRES}@{OLD}\n")
        self.write(Path("specs/proof.md"), f"Ran with {POSTGRES}@{OLD}\n")
        self.registry = FakeRegistry({POSTGRES: NEW, CADDY: OTHER}, {OLD, NEW, OTHER})

    def write(self, relative: Path, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def read(self, relative: str | Path) -> str:
        return (self.root / relative).read_text(encoding="utf-8")

    def run_main(self, *args: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            status = digests.main(list(args), resolve=self.registry)
        return status, out.getvalue(), err.getvalue()

    def test_repin_rewrites_every_file_but_history(self) -> None:
        summary = self.root / "summary.md"
        status, out, _ = self.run_main(
            "repin", str(self.root), "--summary", str(summary)
        )
        self.assertEqual(status, 0)
        lock = json.loads(self.read(digests.LOCK))
        self.assertEqual(lock["systems"][0]["digest"], NEW)
        self.assertEqual(lock["systems"][0]["image"], f"{POSTGRES}@{NEW}")
        self.assertEqual(lock["systems"][1]["digest"], OTHER)
        self.assertEqual(self.read(digests.ENV), digests.render_env(lock))
        self.assertIn(NEW, self.read("infra/compose/compose.yml"))
        self.assertIn(NEW, self.read("README.md"))
        self.assertIn(OLD, self.read("specs/proof.md"))
        self.assertIn(f"{OLD} -> {NEW}", out)
        self.assertIn(
            "`infra/compose/compose.yml`", summary.read_text(encoding="utf-8")
        )
        status, _, _ = self.run_main("verify", str(self.root), "--all-tags")
        self.assertEqual(status, 0)

    def test_no_drift_changes_nothing(self) -> None:
        self.registry.tags[POSTGRES] = OLD
        before = self.read("README.md")
        status, out, _ = self.run_main("repin", str(self.root))
        self.assertEqual(status, 0)
        self.assertIn("repin: OK", out)
        self.assertEqual(self.read("README.md"), before)

    def test_image_filter_limits_the_repin(self) -> None:
        self.registry.tags[CADDY] = NEW.replace("b", "d")
        status, _, _ = self.run_main("repin", str(self.root), "--image", "CADDY_IMAGE")
        self.assertEqual(status, 0)
        lock = json.loads(self.read(digests.LOCK))
        self.assertEqual(lock["systems"][0]["digest"], OLD)
        self.assertEqual(lock["systems"][1]["digest"], NEW.replace("b", "d"))

    def test_unknown_system_fails(self) -> None:
        status, _, err = self.run_main("repin", str(self.root), "--image", "mysql")
        self.assertEqual(status, 1)
        self.assertIn("unknown system(s) mysql", err)

    def test_shared_old_digest_is_refused(self) -> None:
        self.lock["systems"][1] = {
            "id": "postgres-copy",
            "image": f"{POSTGRES}@{OLD}",
            "digest": OLD,
        }
        self.write(digests.LOCK, json.dumps(self.lock, indent=2) + "\n")
        status, _, err = self.run_main("repin", str(self.root), "--image", "postgres")
        self.assertEqual(status, 1)
        self.assertIn("also pinned by postgres-copy", err)
        self.assertIn(OLD, self.read("README.md"))

    def test_verify_cli_fails_on_drift_only_when_asked(self) -> None:
        self.assertEqual(self.run_main("verify", str(self.root))[0], 0)
        status, _, err = self.run_main("verify", str(self.root), "--all-tags")
        self.assertEqual(status, 1)
        self.assertIn("POSTGRES_IMAGE", err)


if __name__ == "__main__":
    unittest.main(verbosity=1)
