"""Exercise the actual backup cleanup function without Docker or credentials."""

from pathlib import Path
import subprocess
import tempfile


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    source = (root / "tools/backup/backup.sh").read_text()
    cleanup = source.split("cleanup() {", 1)[1].split("\ntrap cleanup", 1)[0]
    for stopped, services, initial, resume in (
        ("true", "api rustfs", 0, 0),
        ("true", "api rustfs", 0, 17),
        ("true", "api rustfs", 9, 0),
        ("true", "api rustfs", 9, 17),
        ("false", "api rustfs", 0, 17),
        ("true", "", 0, 17),
    ):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary) / "stage"
            stage.mkdir()
            result = subprocess.run(
                [
                    "/bin/sh",
                    "-c",
                    """
set -eu
compose() {
  [ "$*" = 'start --wait --wait-timeout 420 api rustfs' ] || return 99
  printf '%s' invoked > "$marker"
  echo 'private-output-must-not-escape' >&2
  return "$resume"
}
cleanup() {"""
                    + cleanup
                    + """
trap cleanup EXIT
exit "$initial"
""",
                ],
                env={
                    "PATH": "/usr/bin:/bin",
                    "stage": str(stage),
                    "marker": str(Path(temporary) / "called"),
                    "writers_stopped": stopped,
                    "restart_services": services,
                    "initial": str(initial),
                    "resume": str(resume),
                    "project": "synthetic-test",
                    "manifest_output_tmp": "",
                },
                capture_output=True,
                timeout=5,
                check=False,
            )
            invoked = stopped == "true" and bool(services)
            expected = initial or (1 if invoked and resume else 0)
            assert result.returncode == expected
            assert (Path(temporary) / "called").exists() == invoked
            assert not stage.exists()
            assert (b"backup: OK:" in result.stdout) == (expected == 0)
            assert (b"failed to resume" in result.stderr) == bool(invoked and resume)
            assert b"private-output" not in result.stdout + result.stderr
    print(
        "backup-resume: checked restart, failure propagation, original error preservation, cleanup and private-output suppression passed"
    )


if __name__ == "__main__":
    main()
