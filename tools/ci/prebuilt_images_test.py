#!/usr/bin/env python3
"""Self-tests of tools/ci/prebuilt_images.py (python3 -I, no network, no Docker)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from collections.abc import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci import prebuilt_images as pi  # noqa: E402
from tools.testing import image_tags  # noqa: E402

NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
HASH_A = "a" * 24
HASH_B = "b" * 24


def sha(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def created(days: float) -> str:
    return (NOW - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.123456789Z")


class FakeRegistry:
    """GHCR's token, manifest and blob endpoints for one repository."""

    def __init__(
        self, labels: dict[str, str], age_days: float = 1, index: bool = False
    ):
        self.config = json.dumps(
            {"created": created(age_days), "config": {"Labels": labels}}
        ).encode()
        self.manifest = json.dumps(
            {
                "mediaType": "application/vnd.docker.distribution.manifest.v2+json",
                "config": {"digest": sha(self.config)},
            }
        ).encode()
        self.index = (
            json.dumps(
                {
                    "mediaType": "application/vnd.oci.image.index.v1+json",
                    "manifests": [
                        {
                            "digest": sha(self.manifest),
                            "platform": {"os": "linux", "architecture": "amd64"},
                        },
                        {
                            "digest": "sha256:" + "0" * 64,
                            "platform": {"os": "unknown", "architecture": "unknown"},
                        },
                    ],
                }
            ).encode()
            if index
            else None
        )
        self.calls: list[tuple[str, dict[str, str]]] = []
        self.tampered_blob = False

    @property
    def top(self) -> bytes:
        return self.index or self.manifest

    def get(self, url: str, headers: Any) -> tuple[bytes, dict[str, str]]:
        self.calls.append((url, dict(headers)))
        if "/token?" in url:
            return b'{"token": "anonymous"}', {}
        if url.endswith(f"/manifests/{HASH_A}"):
            return self.top, {"Docker-Content-Digest": sha(self.top)}
        if url.endswith(f"/manifests/{sha(self.manifest)}"):
            return self.manifest, {}
        if "/blobs/" in url:
            return (b"x" + self.config if self.tampered_blob else self.config), {}
        raise pi.Unavailable(f"HTTP 404 for {url}")


class Result:
    def __init__(self, code: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode, self.stdout, self.stderr = code, stdout, stderr


class FakeDocker:
    def __init__(self, labels: dict[str, str], digests: list[str], pull: int = 0):
        self.labels, self.digests, self.pull_code = labels, digests, pull
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *arguments: str, timeout: int = 0) -> Result:
        self.calls.append(arguments)
        if arguments[0] == "pull":
            return Result(self.pull_code, stderr="denied")
        if arguments[:2] == ("image", "inspect"):
            return Result(
                stdout=json.dumps(
                    {"Config": {"Labels": self.labels}, "RepoDigests": self.digests}
                )
            )
        return Result()


IMAGE = pi.Image("api", ("api", "worker"), HASH_A)


class BakeTests(unittest.TestCase):
    def test_groups_expand_to_the_targets_of_the_real_bake_file(self) -> None:
        self.assertEqual(
            pi.expand(["build"]),
            [
                "api",
                "worker",
                "proxy",
                "web",
                "pwa",
                "public",
                "survey-validator",
                "campaign-site",
            ],
        )
        self.assertEqual(pi.expand(["survey-foundation"]), ["api", "survey-validator"])
        self.assertEqual(pi.expand(["api, proxy"]), ["api", "proxy"])

    def test_every_bake_target_is_a_hashed_compose_build(self) -> None:
        text = pi.BAKE_FILE.read_text(encoding="utf-8")
        self.assertEqual(set(pi.bake_targets(text)), set(image_tags.BUILDS))

    def test_bake_builds_what_the_hash_describes(self) -> None:
        """main publishes bake output under the Compose build's hash."""
        text = pi.BAKE_FILE.read_text(encoding="utf-8")
        for name, body in re.findall(r'(?ms)^target "([a-z0-9-]+)" \{\n(.*?)^\}', text):
            with self.subTest(target=name):
                found = dict(
                    re.findall(r'(?m)^  (context|dockerfile) = "([^"]+)"$', body)
                )
                self.assertEqual(found, image_tags.BUILDS[name])
                self.assertNotRegex(body, r"(?m)^  (args|target|secret|ssh) =")

    def test_unknown_names_are_errors(self) -> None:
        with self.assertRaises(ValueError):
            pi.expand(["api,nope"])

    def test_services_with_one_build_share_one_image(self) -> None:
        images, misses = pi.images_for(["api", "worker", "web"], lambda s: HASH_A)
        self.assertEqual(misses, {})
        self.assertEqual(
            {(image.name, image.services) for image in images},
            {("api", ("api", "worker")), ("web", ("web",))},
        )
        self.assertEqual(
            images[0].tag, f"ghcr.io/bjoernschotte/leonaid-ci/api:{HASH_A}"
        )

    def test_unhashable_services_are_misses(self) -> None:
        def hasher(service: str) -> str:
            raise image_tags.Unsupported("FROM without digest")

        images, misses = pi.images_for(["api", "other"], hasher)
        self.assertEqual(images, [])
        self.assertEqual(set(misses), {"api", "other"})


class RegistryTests(unittest.TestCase):
    def resolve(self, fake: FakeRegistry) -> pi.Remote:
        return pi.Registry(f"{pi.NAMESPACE}/api", get=fake.get).resolve(HASH_A)

    def test_resolves_digest_labels_and_age(self) -> None:
        fake = FakeRegistry({pi.HASH_LABEL: HASH_A})
        remote = self.resolve(fake)
        self.assertEqual(remote.digest, sha(fake.manifest))
        self.assertEqual(remote.labels[pi.HASH_LABEL], HASH_A)
        self.assertEqual(
            remote.created, NOW - timedelta(days=1) + timedelta(microseconds=123456)
        )
        self.assertNotIn("Authorization", fake.calls[0][1], "pull token is anonymous")

    def test_index_uses_the_linux_amd64_image_and_keeps_the_index_digest(self) -> None:
        fake = FakeRegistry({pi.HASH_LABEL: HASH_A}, index=True)
        self.assertEqual(self.resolve(fake).digest, sha(fake.top))

    def test_tampered_content_is_rejected(self) -> None:
        fake = FakeRegistry({pi.HASH_LABEL: HASH_A})
        fake.tampered_blob = True
        with self.assertRaises(pi.Unavailable):
            self.resolve(fake)

        def lying(url: str, headers: Any) -> tuple[bytes, dict[str, str]]:
            body, found = FakeRegistry({pi.HASH_LABEL: HASH_A}).get(url, headers)
            return body, {
                **found,
                "Docker-Content-Digest": "sha256:" + "1" * 64,
            } if found else {}

        with self.assertRaises(pi.Unavailable):
            pi.Registry("x", get=lying).resolve(HASH_A)

    def test_a_token_is_sent_only_to_the_token_endpoint_as_basic_auth(self) -> None:
        fake = FakeRegistry({pi.HASH_LABEL: HASH_A})
        pi.Registry(f"{pi.NAMESPACE}/api", "secret", get=fake.get).resolve(HASH_A)
        self.assertTrue(fake.calls[0][1]["Authorization"].startswith("Basic "))
        self.assertTrue(
            all(
                call[1]["Authorization"] == "Bearer anonymous"
                for call in fake.calls[1:]
            )
        )

    def test_redirects_to_another_host_drop_the_token(self) -> None:
        handler = pi._SameHostRedirect()
        request = urllib.request.Request(
            "https://ghcr.io/v2/x/blobs/y", headers={"Authorization": "Bearer t"}
        )
        moved = handler.redirect_request(
            request,
            io.BytesIO(),
            307,
            "moved",
            {},
            "https://pkg-containers.example/blob",
        )
        assert moved is not None
        self.assertFalse(moved.has_header("Authorization"))
        same = handler.redirect_request(
            request, io.BytesIO(), 307, "moved", {}, "https://ghcr.io/v2/z"
        )
        assert same is not None
        self.assertTrue(same.has_header("Authorization"))

    def test_remote_checks_hash_label_and_age(self) -> None:
        good = pi.Remote("d", {pi.HASH_LABEL: HASH_A}, NOW - timedelta(days=1))
        pi.check_remote(IMAGE, good, NOW, pi.PULL_MAX_AGE)
        for remote in (
            pi.Remote("d", {pi.HASH_LABEL: HASH_B}, NOW),
            pi.Remote("d", {}, NOW),
            pi.Remote("d", {pi.HASH_LABEL: HASH_A}, NOW - timedelta(days=29, hours=1)),
        ):
            with self.subTest(remote=remote), self.assertRaises(pi.Unavailable):
                pi.check_remote(IMAGE, remote, NOW, pi.PULL_MAX_AGE)
        # The harness limit pull sets must outlast every image it accepts.
        self.assertLess(pi.PULL_MAX_AGE, timedelta(days=pi.CI_MAX_AGE_DAYS))
        old = pi.Remote("d", {pi.HASH_LABEL: HASH_A}, NOW - timedelta(days=400))
        pi.check_remote(IMAGE, old, NOW, None)


class FetchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.registry = FakeRegistry({pi.HASH_LABEL: HASH_A})
        self.pinned = f"{IMAGE.repository}@{sha(self.registry.manifest)}"

    def fetch(self, docker: FakeDocker) -> str:
        return pi.fetch(
            IMAGE,
            NOW,
            pi.Registry(f"{pi.NAMESPACE}/api", get=self.registry.get),
            docker,
        )

    def test_pulls_by_digest_and_tags_every_service(self) -> None:
        docker = FakeDocker({pi.HASH_LABEL: HASH_A}, [self.pinned])
        self.assertEqual(self.fetch(docker), sha(self.registry.manifest))
        self.assertIn(("pull", "--quiet", self.pinned), docker.calls)
        self.assertIn(("tag", self.pinned, f"leonaid-local/api:{HASH_A}"), docker.calls)
        self.assertIn(
            ("tag", self.pinned, f"leonaid-local/worker:{HASH_A}"), docker.calls
        )

    def test_failed_pull_is_a_miss(self) -> None:
        docker = FakeDocker({pi.HASH_LABEL: HASH_A}, [self.pinned], pull=1)
        with self.assertRaises(pi.Unavailable):
            self.fetch(docker)
        self.assertFalse(any(call[0] == "tag" for call in docker.calls))

    def test_pulled_image_with_another_hash_is_removed(self) -> None:
        docker = FakeDocker({pi.HASH_LABEL: HASH_B}, [self.pinned])
        with self.assertRaises(pi.Unavailable):
            self.fetch(docker)
        self.assertIn(("image", "rm", self.pinned), docker.calls)
        self.assertFalse(any(call[0] == "tag" for call in docker.calls))

    def test_pulled_image_without_the_digest_is_removed(self) -> None:
        docker = FakeDocker({pi.HASH_LABEL: HASH_A}, [])
        with self.assertRaises(pi.Unavailable):
            self.fetch(docker)
        self.assertIn(("image", "rm", self.pinned), docker.calls)

    def test_mismatching_remote_label_is_never_pulled(self) -> None:
        self.registry = FakeRegistry({pi.HASH_LABEL: HASH_B})
        docker = FakeDocker({pi.HASH_LABEL: HASH_B}, [])
        with self.assertRaises(pi.Unavailable):
            self.fetch(docker)
        self.assertEqual(docker.calls, [])


class PullTests(unittest.TestCase):
    def test_kill_switch_builds_everything(self) -> None:
        for value in ("off", "OFF", "false", "0"):
            build, report = pi.pull(
                ["default"], {pi.KILL_SWITCH: value}, fetcher=self.never
            )
            self.assertEqual(build, pi.expand(["default"]))
            self.assertIn("off", report[0])

    def test_disabled_step_builds_everything(self) -> None:
        build, _ = pi.pull(["api"], {"PREBUILT_ENABLED": "false"}, fetcher=self.never)
        self.assertEqual(build, ["api"])

    def never(self, image: pi.Image, now: datetime) -> str:
        raise AssertionError("must not fetch")

    def test_hits_are_not_built_misses_and_errors_are(self) -> None:
        def fetcher(image: pi.Image, now: datetime) -> str:
            if image.name == "api":
                return "sha256:" + "2" * 64
            if image.name == "web":
                raise pi.Unavailable("HTTP 401")
            raise RuntimeError("boom")

        build, report = pi.pull(
            ["api,worker,web,proxy"],
            {},
            hasher=lambda s: HASH_A,
            fetcher=fetcher,
            now=NOW,
        )
        self.assertEqual(build, ["web", "proxy"])
        self.assertTrue(any(line.startswith("hit  api+worker") for line in report))
        self.assertTrue(any("unexpected RuntimeError" in line for line in report))

    def test_a_shared_image_miss_builds_all_its_services(self) -> None:
        def fetcher(image: pi.Image, now: datetime) -> str:
            raise pi.Unavailable("HTTP 404")

        build, _ = pi.pull(["default"], {}, hasher=lambda s: HASH_A, fetcher=fetcher)
        self.assertEqual(build, pi.expand(["default"]))

    def test_main_writes_the_build_list_and_never_fails_on_registry_errors(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "output"
            environ = {
                "GITHUB_OUTPUT": str(output),
                # No Docker, no network: hashing or fetching fails, both misses.
                "DOCKER_DEFAULT_PLATFORM": "linux/amd64",
                "PATH": "/nonexistent",
            }
            original = pi.fetch

            def offline(image: pi.Image, now: datetime, *rest: Any) -> str:
                raise pi.Unavailable("offline")

            pi.fetch = offline  # type: ignore[assignment]
            try:
                self.assertEqual(pi.main(["pull", "survey-foundation"], environ), 0)
            finally:
                pi.fetch = original
            self.assertEqual(output.read_text(), "bake=api,survey-validator\nhits=0\n")

    def test_hits_raise_the_harness_age_limit_for_later_steps(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output, env = Path(directory) / "output", Path(directory) / "env"
            environ = {"GITHUB_OUTPUT": str(output), "GITHUB_ENV": str(env)}
            original = pi.pull
            pi.pull = lambda targets, environ: (["proxy"], ["hit  api"])  # type: ignore[assignment,misc]
            try:
                self.assertEqual(pi.main(["pull", "api,proxy"], environ), 0)
            finally:
                pi.pull = original
            self.assertEqual(output.read_text(), "bake=proxy\nhits=1\n")
            self.assertEqual(
                env.read_text(), f"LEONAID_IMAGE_MAX_AGE_DAYS={pi.CI_MAX_AGE_DAYS}\n"
            )

    def test_outputs_are_single_lines(self) -> None:
        with self.assertRaises(ValueError):
            pi.write_output({"GITHUB_OUTPUT": os.devnull}, bake="api\nhits=9")


class SecretTests(unittest.TestCase):
    def test_forbidden_files(self) -> None:
        self.assertEqual(
            pi.forbidden_paths(
                [
                    "app/.env",
                    "./app/.env.local",
                    ".env.production",
                    "app/.env.example",
                    "srv/sessions.env",
                    "root/.ssh/id_ed25519",
                    "root/.docker/config.json",
                    "app/.git/config",
                    "app/src/env.py",
                    "app/.envrc.sample",
                    "app/.environment",
                ]
            ),
            sorted(
                [
                    "app/.env",
                    "app/.env.local",
                    ".env.production",
                    "srv/sessions.env",
                    "root/.ssh/id_ed25519",
                    "root/.docker/config.json",
                    "app/.git/config",
                ]
            ),
        )

    def test_credential_like_config(self) -> None:
        config = {
            "Config": {
                "Env": [
                    "PATH=/usr/bin",
                    "API_TOKEN=abc",
                    "SECRET_KEY=",
                    "DB_PASSWORD=x",
                ],
                "Labels": {pi.HASH_LABEL: HASH_A, "deploy.token": "t"},
            }
        }
        self.assertEqual(
            pi.secret_environment(config),
            ["API_TOKEN", "DB_PASSWORD", "label deploy.token"],
        )

    def test_archive_names(self) -> None:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            for name in ("app/main.py", "app/.env"):
                info = tarfile.TarInfo(name)
                archive.addfile(info, io.BytesIO(b""))
        buffer.seek(0)
        names = pi.archive_names(buffer)
        self.assertEqual(pi.forbidden_paths(names), ["app/.env"])


class PlanAndPublishTests(unittest.TestCase):
    environ = {"GITHUB_SHA": "c" * 40, "GITHUB_TOKEN": "t"}

    def test_plan_publishes_missing_and_foreign_images_only(self) -> None:
        remotes = {
            # Republishing cannot make an image younger (cached layers).
            "api": pi.Remote("d", {pi.HASH_LABEL: HASH_A}, NOW - timedelta(days=90)),
            "web": pi.Remote("d", {pi.HASH_LABEL: HASH_B}, NOW),
            "pwa": pi.Remote("d", {}, NOW),
        }

        def resolver(image: pi.Image) -> pi.Remote:
            if image.name not in remotes:
                raise pi.Unavailable("HTTP 404")
            return remotes[image.name]

        todo, override, _ = pi.plan(
            ["api,worker,web,pwa,proxy"], self.environ, lambda s: HASH_A, resolver, NOW
        )
        self.assertEqual([image.name for image in todo], ["web", "pwa", "proxy"])
        self.assertEqual(
            override["target"]["web"],
            {
                "tags": [f"ghcr.io/bjoernschotte/leonaid-ci/web:{HASH_A}"],
                "labels": {
                    pi.HASH_LABEL: HASH_A,
                    pi.REVISION_LABEL: "c" * 40,
                    pi.SOURCE_LABEL: pi.SOURCE,
                },
            },
        )

    def test_plan_needs_the_commit(self) -> None:
        with self.assertRaises(ValueError):
            pi.plan(
                ["api"], {}, lambda s: HASH_A, lambda i: pi.Remote("d", {}, NOW), NOW
            )

    def publish(
        self, docker: FakeDocker, problems: list[str], anonymous: bool = True
    ) -> tuple[bool, list[str]]:
        def resolver(image: pi.Image, token: str | None) -> pi.Remote:
            if token is None and not anonymous:
                raise pi.Unavailable("HTTP 401")
            return pi.Remote(
                "sha256:" + "3" * 64,
                {pi.HASH_LABEL: image.content},
                datetime.now(timezone.utc),
            )

        return pi.publish([IMAGE], self.environ, docker, lambda ref: problems, resolver)

    def test_unclean_images_are_never_pushed(self) -> None:
        docker = FakeDocker({pi.HASH_LABEL: HASH_A}, [])
        ok, report = self.publish(docker, ["forbidden file app/.env"])
        self.assertFalse(ok)
        self.assertFalse(any(call[0] == "push" for call in docker.calls))
        self.assertIn("app/.env", report[0])

    def test_images_without_the_label_are_never_pushed(self) -> None:
        docker = FakeDocker({}, [])
        ok, _ = self.publish(docker, [])
        self.assertFalse(ok)
        self.assertFalse(any(call[0] == "push" for call in docker.calls))

    def test_push_and_visibility_warning(self) -> None:
        docker = FakeDocker({pi.HASH_LABEL: HASH_A}, [])
        ok, report = self.publish(docker, [], anonymous=False)
        self.assertTrue(ok)
        self.assertIn(("push", "--quiet", IMAGE.tag), docker.calls)
        self.assertTrue(report[0].startswith("pushed "))
        self.assertTrue(
            report[1].startswith("::warning title=GHCR package not public::")
        )


class CleanupTests(unittest.TestCase):
    def version(self, number: int, tags: list[str], days: int) -> dict[str, Any]:
        return {
            "id": number,
            "created_at": created(days),
            "metadata": {"container": {"tags": tags}},
        }

    def test_stale_versions(self) -> None:
        versions = [
            self.version(1, [HASH_A], 90),  # referenced by main: kept
            self.version(2, [HASH_B], 40),  # unreferenced, old: deleted
            self.version(3, [HASH_B], 10),  # young: kept
            self.version(4, [], 31),  # untagged, old: deleted
            self.version(5, ["latest", HASH_B], 99),  # foreign tag: never touched
        ]
        stale = pi.stale_versions(versions, {HASH_A}, NOW)
        self.assertEqual([entry[0] for entry in stale], [2, 4])

    def fake_api(
        self, deleted: list[str], missing: frozenset[str] = frozenset()
    ) -> Callable[[str, str, str], Any]:
        def call(method: str, path: str, token: str) -> Any:
            self.assertEqual(token, "t")
            if method == "DELETE":
                deleted.append(path)
                return None
            name = path.split("%2F", 1)[1].split("/", 1)[0]
            if name in missing:
                raise urllib.error.HTTPError(path, 404, "missing", {}, None)  # type: ignore[arg-type]
            return [self.version(7, [HASH_B], 45), self.version(8, [HASH_A], 45)]

        return call

    def test_dry_run_deletes_nothing(self) -> None:
        deleted: list[str] = []
        ok, report = pi.cleanup(
            True, "t", lambda s: HASH_A, self.fake_api(deleted), NOW
        )
        self.assertTrue(ok)
        self.assertEqual(deleted, [])
        self.assertTrue(any("would delete 7" in line for line in report))
        self.assertFalse(any("8 (" in line for line in report))

    def test_real_run_deletes_only_unreferenced_versions(self) -> None:
        deleted: list[str] = []
        ok, _ = pi.cleanup(
            False,
            "t",
            lambda s: HASH_A,
            self.fake_api(deleted, frozenset({"proxy"})),
            NOW,
        )
        self.assertTrue(ok)
        self.assertTrue(deleted)
        self.assertTrue(all(path.endswith("/versions/7") for path in deleted))
        self.assertFalse(any("proxy" in path for path in deleted))

    def test_without_every_current_hash_nothing_is_deleted(self) -> None:
        def hasher(service: str) -> str:
            raise image_tags.Unsupported("unknown")

        deleted: list[str] = []
        ok, _ = pi.cleanup(False, "t", hasher, self.fake_api(deleted), NOW)
        self.assertFalse(ok)
        self.assertEqual(deleted, [])


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
        self.assertIn("cleanup", result.stdout)


if __name__ == "__main__":
    unittest.main()
