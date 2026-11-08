"""The order-mail contract asks for a delivery-window mail only where one is booked.

Regression: the CI smoke leg filters tests/e2e/public-orders.spec.mjs to the
guided-form case, which books no delivery window, but order_mails.py still
required a mailed window and failed every smoke run (CI job 128554403652).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tools.public_orders.order_mails import ContractFailure, require_window_proof

ROOT = Path(__file__).resolve().parents[2]
TEST_SH = ROOT / "tools/public_orders/test.sh"
SPEC = ROOT / "tests/e2e/public-orders.spec.mjs"


def test_window_proof_required_only_when_expected() -> None:
    with pytest.raises(ContractFailure, match="delivery window"):
        require_window_proof(0, expected=True)
    require_window_proof(1, expected=True)
    require_window_proof(0, expected=False)
    require_window_proof(2, expected=False)


def spec_tests() -> dict[str, str]:
    """Each browser test's title mapped to its body."""

    source = SPEC.read_text(encoding="utf-8")
    starts = list(re.finditer(r'^test\("((?:[^"\\]|\\.)*)"', source, re.M))
    return {
        match.group(1): source[
            match.start() : starts[index + 1].start()
            if index + 1 < len(starts)
            else len(source)
        ]
        for index, match in enumerate(starts)
    }


def books_window(body: str) -> bool:
    """The test submits an order (expects success) with a window chosen."""

    return "deliveryWindowId" in body and "submitOrderResult(" in body


def test_smoke_leg_and_full_leg_agree_with_the_spec() -> None:
    script = TEST_SH.read_text(encoding="utf-8")
    grep = re.search(r'LEONAID_E2E_SMOKE:\+--grep "([^"]+)"', script)
    assert grep, "the smoke filter of the browser step is missing"
    tests = spec_tests()
    smoke = [title for title in tests if re.search(grep.group(1), title)]
    assert smoke, f"the smoke filter matches no test: {grep.group(1)}"
    smoke_books = any(books_window(tests[title]) for title in smoke)
    assert any(books_window(body) for body in tests.values()), (
        "no browser test books a delivery window for the full leg"
    )

    branch = re.search(
        r'if \[ -n "\$\{LEONAID_E2E_SMOKE:-\}" \]; then\n'
        r"  order_mails confirmations(?P<smoke>[^\n]*)\n"
        r"else\n"
        r"  order_mails confirmations(?P<full>[^\n]*)\n"
        r"fi\n",
        script,
    )
    assert branch, "test.sh must choose the window expectation per leg"
    assert script.count("order_mails confirmations") == 2
    assert branch.group("full").strip() == "--expect-delivery-window"
    expected = "--expect-delivery-window" if smoke_books else ""
    assert branch.group("smoke").strip() == expected
