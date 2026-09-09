"""Exercise the real restore entrypoint's scope guards without Docker access."""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys
import tempfile


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as temporary:
        workspace = Path(temporary)

        def refused(expected: str, **changes: str) -> None:
            result = subprocess.run(
                ["/bin/sh", str(root / "tools/backup/restore.sh"), str(root)],
                env={
                    "PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin",
                    "TMPDIR": temporary,
                    "LEONAID_RESTORE_PROJECT": "leonaid-restore-scope-test",
                    "LEONAID_ENV_FILE": str(workspace / "missing-environment"),
                    **changes,
                },
                capture_output=True,
                timeout=5,
                check=False,
            )
            assert result.returncode == 1
            assert result.stdout == b""
            assert result.stderr.decode().strip() == f"restore: ERROR: {expected}"
            assert {path.name for path in workspace.iterdir()} == {
                "leonaid-restore-scope-test.restore.lock"
            }, "Restore leaked staging files beyond the persistent target lock"

        for invalid in ("partial", "CMS", "cms;true", "cms full"):
            refused("unknown restore scope", LEONAID_RESTORE_SCOPE=invalid)
        refused(
            "CMS-only restore requires EmDash topology", LEONAID_RESTORE_SCOPE="cms"
        )
        refused(
            "CMS-only restore requires an explicit verified CMS image",
            LEONAID_RESTORE_SCOPE="cms",
            LEONAID_RESTORE_TOPOLOGY="emdash",
        )
        refused(
            "CMS-only restore cannot resume",
            LEONAID_RESTORE_SCOPE="cms",
            LEONAID_RESTORE_TOPOLOGY="emdash",
            LEONAID_RESTORE_CMS_IMAGE="synthetic-image-still-requires-verification",
            LEONAID_RESTORE_RESUME="true",
        )
        # Valid choices proceed only as far as the missing environment guard.
        # No Docker executable/socket or operator credentials are supplied.
        refused("Environment-Datei fehlt")
        refused("Environment-Datei fehlt", LEONAID_RESTORE_SCOPE="full")
        refused(
            "Environment-Datei fehlt",
            LEONAID_RESTORE_SCOPE="cms",
            LEONAID_RESTORE_TOPOLOGY="emdash",
            LEONAID_RESTORE_CMS_IMAGE="synthetic-image-still-requires-verification",
        )
    print(
        "restore-scope: actual shell rejects invalid scope/topology/missing image before Docker; full default retained and preflight staging cleaned"
    )


if __name__ == "__main__":
    main()
