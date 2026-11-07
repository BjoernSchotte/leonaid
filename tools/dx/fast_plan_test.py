#!/usr/bin/env python3
"""check-fast selection against the real workspace manifests."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.dx.fast_plan import SCRIPTS, plan

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).parents[2])


class FastPlanTests(unittest.TestCase):
    def test_leaf_app_selects_only_itself(self) -> None:
        scripts, _ = plan(ROOT, ["apps/web/src/main.tsx"])
        self.assertEqual(scripts, ["typecheck:web"])

    def test_shared_package_selects_its_dependents(self) -> None:
        scripts, _ = plan(ROOT, ["packages/api-client/src/generated.ts"])
        for script in (
            "typecheck:api-client",
            "typecheck:features",
            "typecheck:web",
            "typecheck:pwa",
            "typecheck:public",
            "typecheck:campaign-site",
        ):
            self.assertIn(script, scripts)
        self.assertNotIn("typecheck:docs", scripts)

    def test_transitive_dependents_without_own_script(self) -> None:
        # surveys has no typecheck script; features (and through it web/pwa)
        # and public depend on it.
        scripts, _ = plan(ROOT, ["packages/surveys/src/index.ts"])
        self.assertTrue(
            {"typecheck:features", "typecheck:web", "typecheck:pwa", "typecheck:public"}
            <= set(scripts)
        )

    def test_root_inputs_select_everything(self) -> None:
        for changed in (["bun.lock"], ["package.json"], ["ALL"]):
            scripts, _ = plan(ROOT, changed)
            self.assertEqual(scripts, list(SCRIPTS.values()))

    def test_python_only_change_selects_nothing(self) -> None:
        self.assertEqual(plan(ROOT, ["src/leonaid/app.py", "tools/dx/x.py"]), ([], []))

    def test_prettier_gets_existing_files_in_scope(self) -> None:
        _, prettier = plan(
            ROOT,
            ["package.json", "apps/web/package.json", "apps/web/gone.ts", "src/x.py"],
        )
        self.assertEqual(prettier, ["apps/web/package.json", "package.json"])


if __name__ == "__main__":
    unittest.main(argv=sys.argv[:1])
