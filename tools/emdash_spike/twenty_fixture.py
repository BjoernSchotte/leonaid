"""EmDash order cases: Twenty from the migrated CI fixture, not a cold boot (E-039).

Restores only Twenty's volumes of the prepared fixture into the case's own
project; Core and every other volume start empty, as before. The fresh
Twenty installation stays proven by the Golden installation run.

Usage: twenty_fixture.py ROOT PROJECT   (CI only, before the first start)
"""

import os
from pathlib import Path
import shutil
import sys

# The harness modules, as tools/testing/seed_fixture.py imports them (that
# directory is outside the typed sources).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "testing"))
from ci_fixture import validate  # type: ignore[import-not-found]  # noqa: E402
from shared_stack import SharedStack  # type: ignore[import-not-found]  # noqa: E402

TWENTY = {"twenty-postgres-data", "twenty-redis-data", "twenty-server-data"}

root, project = Path(sys.argv[1]).resolve(), sys.argv[2]
fixture = Path(os.environ["LEONAID_CI_FIXTURE"])
stack = SharedStack(root, "golden")
stack.project = project
stack.compose[stack.compose.index("--project-name") + 1] = project
try:
    for resource in ("containers", "volumes"):
        if stack.inventory(resource):
            raise RuntimeError("Twenty fixture requires empty owned resources")
    stack.fixture_metadata = validate(root, fixture)
    if not TWENTY <= set(stack.fixture_metadata["volumes"]):
        raise RuntimeError("Prepared fixture lacks Twenty's volumes")
    stack.unused_volumes = frozenset(
        f"{project}_{name}"
        for name in stack.fixture_metadata["volumes"]
        if name not in TWENTY
    )
    stack.import_fixture(fixture)
    print("emdash-twenty-fixture: OK: migrated Twenty volumes restored")
finally:
    shutil.rmtree(stack.directory)
