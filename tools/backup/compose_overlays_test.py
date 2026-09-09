"""Execute the real shell overlay-list boundary against actual files."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile


def main() -> None:
    helper = Path(__file__).with_name("compose-overlays.sh").resolve()
    with tempfile.TemporaryDirectory() as temporary:
        parent = Path(temporary)
        root = parent / "repository with spaces"
        root.mkdir()
        (root / "valid.yml").write_text("services: {}\n")
        listing = root / "overlays"

        def run(expected: int, **changes: str) -> None:
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    'fail() { exit 1; }; . "$helper"; validate_recovery_overlays',
                ],
                env={
                    **os.environ,
                    "helper": str(helper),
                    "root": str(root),
                    "recovery_overlay_list": str(listing),
                    "compose_overlay": "",
                    "compose_overlay_secondary": "",
                    **changes,
                },
                capture_output=True,
                timeout=5,
                check=False,
            )
            assert result.returncode == expected

        listing.write_text("valid.yml\n")
        run(0)
        run(0, recovery_overlay_list="")
        run(1, compose_overlay="valid.yml")
        run(1, compose_overlay_secondary="valid.yml")
        for content in (
            "",
            "\n",
            "../valid.yml\n",
            "/valid.yml\n",
            "missing.yml\n",
            "valid.yml;echo unsafe\n",
            "valid.json\n",
            "valid.yml\n" * 17,
        ):
            listing.write_text(content)
            run(1)
        listing.write_text("valid.yml")
        run(0)  # Final newline is optional, but an empty entry is not.
        outside = parent / "outside.yml"
        outside.write_text("services: {}\n")
        (root / "linked.yml").symlink_to(outside)
        listing.write_text("linked.yml\n")
        run(1)
        (root / "escape").symlink_to(parent, target_is_directory=True)
        listing.write_text("escape/outside.yml\n")
        run(1)
        listing.unlink()
        listing.symlink_to(outside)
        run(1)
    print(
        "compose-overlays-test: real files prove valid relative paths, spaces, conflict, traversal, metacharacter, count and symlink denial"
    )


if __name__ == "__main__":
    main()
