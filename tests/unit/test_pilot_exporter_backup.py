"""The backup signal accepts both backup topologies (tools/backup/manifest.py)."""

import json
from datetime import datetime, timezone
from pathlib import Path

from leonaid.entrypoints.monitoring.exporter import _backup_metrics

PROJECT = "leonaid-production-club-111"
LEGACY = ("core.dump", "twenty.dump", "twenty-storage.tar", "rustfs-data.tar")
CMS = ("emdash.dump", "cms-bootstrap-state.tar")


def manifest(path: Path, version: int, names: tuple[str, ...]) -> Path:
    path.write_text(
        json.dumps(
            {
                "schemaVersion": version,
                "sourceProject": PROJECT,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "files": {name: {"sha256": "a" * 64, "size": 1} for name in names},
            }
        ),
        encoding="utf-8",
    )
    return path


def valid(path: Path) -> int:
    return _backup_metrics(path, expected_project=PROJECT)[0]


def test_legacy_and_cms_backups_with_optional_tls_state_are_valid(
    tmp_path: Path,
) -> None:
    assert valid(manifest(tmp_path / "a.json", 1, LEGACY)) == 1
    # Every pilot backup since specs/multi-domain stage 1 carries caddy-data.
    assert valid(manifest(tmp_path / "b.json", 1, (*LEGACY, "caddy-data.tar"))) == 1
    assert valid(manifest(tmp_path / "c.json", 2, (*LEGACY, *CMS))) == 1
    assert (
        valid(manifest(tmp_path / "d.json", 2, (*LEGACY, *CMS, "caddy-data.tar"))) == 1
    )


def test_topology_and_inventory_mismatches_are_invalid(tmp_path: Path) -> None:
    # A CMS backup without its CMS data, a legacy one carrying CMS files.
    assert valid(manifest(tmp_path / "a.json", 2, LEGACY)) == 0
    assert valid(manifest(tmp_path / "b.json", 1, (*LEGACY, *CMS))) == 0
    assert valid(manifest(tmp_path / "c.json", 1, LEGACY[:3])) == 0
    assert valid(manifest(tmp_path / "d.json", 1, (*LEGACY, "unknown.tar"))) == 0
    assert valid(manifest(tmp_path / "e.json", 3, (*LEGACY, *CMS))) == 0
