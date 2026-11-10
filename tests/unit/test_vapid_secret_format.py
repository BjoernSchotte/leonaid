"""The VAPID key of Web Push as bootstrap and the pilot tooling create it."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from leonaid.adapters.web_push import VapidSigner
from tools.dx.generate_secrets import generate_p256_private_key, p256_private_key
from tools.pilot_deployment.validate import vapid_problem
from tools.pilot_install.production_secrets import GENERATORS
from tools.testing import ci_fixture

ROOT = Path(__file__).resolve().parents[2]
SUBJECT = "mailto:betrieb@lions-musterstadt.de"


def test_bootstrap_writes_a_key_the_sender_accepts(tmp_path: Path) -> None:
    template = tmp_path / "template"
    output = tmp_path / "environment"
    template.write_text(
        "LEONAID_VAPID_PRIVATE_KEY=__GENERATE_P256_PRIVATE_KEY__\n"
        "LEONAID_VAPID_SUBJECT=mailto:push@leonaid.invalid\n"
    )
    script = ROOT / "tools/dx/generate_secrets.py"
    for _ in range(2):
        subprocess.run(
            [sys.executable, str(script), str(template), str(output)],
            check=True,
            capture_output=True,
        )
    values = dict(line.split("=", 1) for line in output.read_text().splitlines())
    signer = VapidSigner(
        values["LEONAID_VAPID_PRIVATE_KEY"], values["LEONAID_VAPID_SUBJECT"]
    )
    assert len(signer.public_key) == 87
    # The second run kept the key: a new key would end every subscription.
    first = values["LEONAID_VAPID_PRIVATE_KEY"]
    subprocess.run(
        [sys.executable, str(script), str(template), str(output)],
        check=True,
        capture_output=True,
    )
    assert f"LEONAID_VAPID_PRIVATE_KEY={first}\n" in output.read_text()


def test_the_env_template_asks_for_the_key_and_a_subject() -> None:
    template = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "LEONAID_VAPID_PRIVATE_KEY=__GENERATE_P256_PRIVATE_KEY__\n" in template
    assert "LEONAID_VAPID_SUBJECT=mailto:" in template
    pilot = (ROOT / "infra/pilot/production.env.example").read_text(encoding="utf-8")
    assert "LEONAID_VAPID_PRIVATE_KEY=__RANDOM_P256_PRIVATE_KEY__\n" in pilot
    assert "LEONAID_VAPID_SUBJECT=mailto:" in pilot


def test_generated_keys_are_scalars_of_the_p256_group() -> None:
    order = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551
    assert p256_private_key(bytes(32)) is None
    assert p256_private_key(order.to_bytes(32, "big")) is None
    assert p256_private_key((order - 1).to_bytes(32, "big")) is not None
    assert p256_private_key(bytes(31)) is None
    for generate in (
        generate_p256_private_key,
        GENERATORS["__RANDOM_P256_PRIVATE_KEY__"],
    ):
        keys = {generate() for _ in range(20)}
        assert len(keys) == 20
        for key in keys:
            VapidSigner(key, SUBJECT)
            assert vapid_problem(key, SUBJECT) is None


def test_the_synthetic_test_environment_has_a_usable_key() -> None:
    values = dict(
        line.split("=", 1)
        for line in ci_fixture.environment(ROOT).splitlines()
        if "=" in line and not line.startswith("#")
    )
    VapidSigner(values["LEONAID_VAPID_PRIVATE_KEY"], values["LEONAID_VAPID_SUBJECT"])


def test_the_pilot_checks_name_what_is_wrong_with_push_settings() -> None:
    key = generate_p256_private_key()
    assert vapid_problem("", "") is None
    assert vapid_problem("", "mailto:operations@example.org") is None
    assert vapid_problem(key, "https://lions-musterstadt.de/kontakt") is None
    for bad_key in ("__RANDOM_P256_PRIVATE_KEY__", "A" * 43, "short", "%" * 43):
        assert "PRIVATE_KEY" in (vapid_problem(bad_key, SUBJECT) or "")
    for subject in (
        "",
        "mailto:operations@example.org",
        "mailto:push@leonaid.invalid",
        "betrieb@lions-musterstadt.de",
        "mailto:@lions-musterstadt.de",
        "http://lions-musterstadt.de",
    ):
        assert "SUBJECT" in (vapid_problem(key, subject) or "")
