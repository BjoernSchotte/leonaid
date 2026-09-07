"""Export fixed diagnostic categories and public source locations, never log text."""

import json
from pathlib import Path
import re
import subprocess
import sys

MARKERS = {
    "disk-space": "no space left on device",
    "docker-unavailable": "Cannot connect to the Docker daemon",
    "subnet-overlap": "Pool overlaps",
    "service-unhealthy": "unhealthy",
    "image-build-failed": "failed to solve",
    "architecture-mismatch": "exec format error",
    "python-module-missing": "ModuleNotFoundError",
    "file-missing": "No such file or directory",
    "permission-denied": "Permission denied",
    "filesystem-readonly": "Read-only file system",
    "javascript-permission-denied": "EACCES",
    "browser-executable-missing": "Executable doesn't exist",
    "browser-launch": "browserType.launch",
    "browser-closed": "Target page, context or browser has been closed",
    "timeout": "TimeoutError",
    "assertion": "AssertionError",
    "browser-assertion": "expect(received)",
    "no-browser-tests": "No tests found",
    "javascript-module-missing": "Cannot find module",
    "javascript-import-missing": "Could not resolve",
    "connection-refused": "Connection refused",
    "network-unreachable": "Network is unreachable",
    "dependency-lock-mismatch": "lockfile had changes",
}
LOCATION = re.compile(
    r"((?:tests|tools|apps|packages|src)/[A-Za-z0-9_./-]+)(?::|\", line )(\d+)"
)


def classify(text: str, public_files: dict[str, int]) -> dict:
    categories = sorted(
        key for key, marker in MARKERS.items() if marker.casefold() in text.casefold()
    )
    locations = set()
    for path, line in LOCATION.findall(text):
        if path in public_files and 0 < int(line) <= public_files[path]:
            locations.add((path, int(line)))
    return {
        "observedMarkers": categories,
        "publicLocations": [
            {"file": path, "line": line} for path, line in sorted(locations)[:30]
        ],
    }


def collect(root: Path) -> dict:
    root = root.resolve()
    tracked = (
        subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
        .decode()
        .split("\0")
    )
    public_files = {}
    for name in tracked:
        path = root / name
        if (
            path.suffix in {".py", ".ts", ".tsx", ".mjs", ".js", ".astro", ".sh"}
            and path.is_file()
            and not path.is_symlink()
        ):
            public_files[name] = len(path.read_text(errors="replace").splitlines())
    checks = json.loads((root / "tools/surveys/gate.json").read_text())["checks"]
    allowed_logs = {
        f"{iteration}-{check['id']}.log"
        for check in checks
        for iteration in range(1, 11)
    }
    logs = []
    for path in sorted((root / ".artifacts/surveys-gate").glob("private-*/*.log")):
        if path.name in allowed_logs:
            logs.append(("gate/" + path.name, path))
    for name in ("infrastructure", "infrastructure-failure"):
        path = root / f".artifacts/foundation-acceptance/{name}.log"
        if path.exists():
            logs.append(("foundation/" + name, path))
    diagnostics = []
    for label, path in logs:
        if path.is_symlink() or any(
            parent.is_symlink() for parent in path.parents if parent != root
        ):
            continue
        with path.open("rb") as stream:
            data = stream.read(2 * 1024 * 1024)
            if path.stat().st_size > len(data):
                stream.seek(max(0, path.stat().st_size - 2 * 1024 * 1024))
                data += stream.read(2 * 1024 * 1024)
        diagnostics.append(
            {"source": label, **classify(data.decode(errors="replace"), public_files)}
        )
    return {
        "schemaVersion": 1,
        "scope": "fixed markers and public locations only; presence does not establish root cause",
        "diagnostics": diagnostics,
    }


if __name__ == "__main__":
    root = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    report = collect(root)
    destination = root / ".artifacts/surveys-gate/results/diagnostics/metadata.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print("Survey diagnostic metadata written; raw logs remain private")
