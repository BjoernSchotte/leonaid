"""Check that image reuse cannot share runtime state or serialize secrets."""

from pathlib import Path
import unittest

from image_cache import override


class ImageCacheTests(unittest.TestCase):
    def test_only_build_image_names_are_overridden(self):
        model = {
            "services": {
                "api": {
                    "build": {"context": "."},
                    "environment": {"SECRET": "must-not-persist"},
                    "volumes": ["private:/data"],
                    "networks": ["private"],
                },
                "db": {"image": "postgres:pinned"},
            }
        }
        result = override(model, Path("/tmp/one-run"))
        self.assertEqual(set(result), {"services"})
        self.assertEqual(set(result["services"]), {"api"})
        self.assertEqual(set(result["services"]["api"]), {"image", "pull_policy"})
        self.assertEqual(result["services"]["api"]["pull_policy"], "never")
        self.assertNotIn("must-not-persist", str(result))
        self.assertEqual(result, override(model, Path("/tmp/one-run")))
        self.assertNotEqual(result, override(model, Path("/tmp/another-run")))


if __name__ == "__main__":
    unittest.main()
