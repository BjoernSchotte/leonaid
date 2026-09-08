"""Name build outputs for one locked aggregate run; never persist Compose secrets."""

import hashlib
import json
from pathlib import Path
import sys


def override(model: dict, directory: Path) -> dict:
    prefix = (
        "leonaid-survey-gate-"
        + hashlib.sha256(str(directory.resolve()).encode()).hexdigest()[:24]
    )
    return {
        "services": {
            name: {"image": f"{prefix}-{name}:local", "pull_policy": "never"}
            for name, service in model["services"].items()
            if "build" in service
        }
    }


if __name__ == "__main__":
    directory = Path(sys.argv[1])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    model = override(json.load(sys.stdin), directory)
    if not model["services"]:
        raise SystemExit("No build services found")
    (directory / "images.json").write_text(json.dumps(model) + "\n")
