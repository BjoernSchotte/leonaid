"""Real-file checks that host ports are chosen once and then kept."""

import os
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools/dx"
TEMPLATE = "LEONAID_HTTP_PORT=__HOST_PORT__\nLEONAID_HTTPS_PORT=__HOST_PORT__\n"


def generate(template: Path, output: Path, **ports: str):
    return subprocess.run(
        [
            sys.executable,
            str(TOOLS / "generate_secrets.py"),
            str(template),
            str(output),
        ],
        env={**os.environ, **ports},
        capture_output=True,
        text=True,
    )


def test_ports_come_from_host_once_and_are_kept(tmp_path: Path) -> None:
    template = tmp_path / "template"
    output = tmp_path / "environment"
    template.write_text(TEMPLATE)
    assert generate(template, output).returncode == 1
    assert not output.exists()

    generate(template, output, LEONAID_HTTP_PORT="28080", LEONAID_HTTPS_PORT="28081")
    expected = "LEONAID_HTTP_PORT=28080\nLEONAID_HTTPS_PORT=28081\n"
    assert output.read_text() == expected

    generate(template, output, LEONAID_HTTP_PORT="8080", LEONAID_HTTPS_PORT="8443")
    assert output.read_text() == expected


def test_verify_rejects_invalid_ports(tmp_path: Path) -> None:
    template = tmp_path / "template"
    template.write_text("LEONAID_ENV=local\nLEONAID_RESET_ALLOWED=true\n" + TEMPLATE)
    for ports, status in (
        ("28080\n", 0),
        ("28081\n", 1),  # same port twice
        ("80\n", 1),  # privileged
    ):
        actual = tmp_path / "actual"
        actual.write_text(
            "LEONAID_ENV=local\nLEONAID_RESET_ALLOWED=true\n"
            f"LEONAID_HTTP_PORT=28081\nLEONAID_HTTPS_PORT={ports}"
        )
        result = subprocess.run(
            [
                sys.executable,
                str(TOOLS / "verify_secrets.py"),
                str(template),
                str(actual),
            ],
            capture_output=True,
        )
        assert result.returncode == status
