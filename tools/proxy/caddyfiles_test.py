"""Guards for the rendered Caddyfiles (stdlib only; validate-caddyfiles.sh runs it).

The map tiles of the delivery tours (specs/krapfentaxi-touren §8.1, D3) open
`img-src` for exactly one origin, the installation's tile server. Nothing
else in the policy changes: scripts and connections stay on 'self'.
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.proxy import caddyfiles  # noqa: E402

TILE_ORIGIN = "{$LEONAID_MAP_TILE_ORIGIN:https://tile.openstreetmap.org}"


def _policies(text: str) -> list[dict[str, str]]:
    found = re.findall(r'^\s*\??Content-Security-Policy "([^"]+)"', text, re.M)
    policies = []
    for policy in found:
        directives: dict[str, str] = {}
        for part in policy.split(";"):
            tokens = part.split()
            if tokens:
                directives[tokens[0]] = " ".join(tokens[1:])
        policies.append(directives)
    return policies


class CaddyfileTests(unittest.TestCase):
    def test_img_src_names_tile_origin_and_connect_src_stays_self(self) -> None:
        for name in caddyfiles.TARGETS:
            with self.subTest(target=name):
                policies = _policies(caddyfiles.render(name))
                self.assertEqual(len(policies), 2)
                for directives in policies:
                    self.assertEqual(
                        directives["img-src"], f"'self' data: blob: {TILE_ORIGIN}"
                    )
                    self.assertEqual(directives["connect-src"], "'self'")
                    self.assertEqual(directives["script-src"], "'self'")
                    self.assertEqual(directives["style-src"], "'self'")

    def test_e2e_tiles_only_in_dev(self) -> None:
        for name in caddyfiles.TARGETS:
            with self.subTest(target=name):
                text = caddyfiles.render(name)
                if name.startswith("dev-"):
                    block = re.search(
                        r"\n\thandle /e2e-tiles/\* \{\n(.*?)\n\t\}", text, re.S
                    )
                    if name == "dev-admin-only":
                        # The admin-only stack proof runs no browser maps.
                        self.assertIsNone(block)
                        continue
                    self.assertIsNotNone(block)
                    assert block is not None
                    body = block.group(1)
                    self.assertIn("header Content-Type image/svg+xml", body)
                    self.assertIn('width="256" height="256"', body)
                    self.assertNotIn("<script", body)
                else:
                    self.assertNotIn("e2e-tiles", text)

    def test_only_member_hosts_allow_geolocation(self) -> None:
        for name in caddyfiles.TARGETS:
            with self.subTest(target=name):
                text = caddyfiles.render(name)
                for snippet, allowed in (
                    ("common_headers", "geolocation=(self)"),
                    ("public_host_headers", "geolocation=()"),
                ):
                    block = re.search(
                        rf"^\({snippet}\) \{{\n(.*?)^\}}", text, re.M | re.S
                    )
                    assert block is not None
                    self.assertIn(allowed, block.group(1))


if __name__ == "__main__":
    unittest.main()
