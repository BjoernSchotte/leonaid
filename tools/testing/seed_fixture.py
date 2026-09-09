"""Prepare the mutation/reset case; the operator reset itself remains a cold reset."""

import json
import os
from pathlib import Path
import re
import shutil
import sys

from shared_stack import SharedStack

root, operator, project = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
if os.environ.get("GITHUB_ACTIONS") != "true" or not re.fullmatch(
    r"leonaid-poc012-test-[0-9]+-[0-9]+", project
):
    raise RuntimeError("Prepared seed case is restricted to its isolated CI harness")
stack = SharedStack(root, "documents")
stack.project = project
stack.compose[stack.compose.index("--project-name") + 1] = project
try:
    for resource in ("containers", "volumes"):
        if stack.inventory(resource):
            raise RuntimeError("Seed fixture requires empty owned resources")
    # Networks already belong to the parent harness. The parent owns cleanup,
    # including failures while materializing these initially empty volumes.
    stack.import_fixture(Path(os.environ["LEONAID_CI_FIXTURE"]))
    target = operator / ".local/twenty"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(stack.directory / "integration.env", target / "integration.env")
    (target / "integration.env").chmod(0o600)
    shutil.copytree(
        stack.directory / "pdfs", operator / ".artifacts/golden-v1/invoices"
    )
    compose = operator / "infra/compose/compose.yml"
    data = json.loads(compose.read_text())
    environment = data["services"]["twenty-server"]["environment"]
    environment["DISABLE_DB_MIGRATIONS"] = "true"
    environment["DISABLE_CRON_JOBS_REGISTRATION"] = "true"
    for service in data["services"].values():
        if "healthcheck" in service:
            # Preserve the original wait budget while probing readiness promptly.
            health = service["healthcheck"]
            interval = health["interval"]
            if not isinstance(interval, str) or not re.fullmatch(
                r"[1-9][0-9]*s", interval
            ):
                raise RuntimeError("Expected a whole-second Compose health interval")
            seconds = int(interval[:-1])
            health["retries"] *= seconds
            health["interval"] = "1s"
    compose.write_text(json.dumps(data))
finally:
    shutil.rmtree(stack.directory)
