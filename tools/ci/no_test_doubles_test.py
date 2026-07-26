#!/usr/bin/env python3
"""Exercise the no-test-double policy with real temporary repositories."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def write_base(source: Path, target: Path) -> None:
    (target / "apps").mkdir(parents=True)
    (target / "packages").mkdir()
    (target / "tests").mkdir()
    shutil.copy(source / "pyproject.toml", target / "pyproject.toml")
    shutil.copy(source / "package.json", target / "package.json")


def expect_failure(checker: Path, root: Path, expected: str) -> None:
    result = subprocess.run(
        [sys.executable, str(checker), str(root)],
        check=False,
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    if result.returncode == 0 or expected not in output:
        raise AssertionError(
            f"Policy-Fall {expected!r} wurde nicht abgewiesen: {output}"
        )


def main() -> None:
    source = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    checker = source / "tools/ci/no_test_doubles.py"
    subprocess.run([sys.executable, str(checker), str(source)], check=True)
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        python_dependency = root / "python-dependency"
        write_base(source, python_dependency)
        pyproject = (python_dependency / "pyproject.toml").read_text(encoding="utf-8")
        (python_dependency / "pyproject.toml").write_text(
            pyproject.replace(
                "dependencies = [",
                'dependencies = [\n  "responses==0.25.7",',
                1,
            ),
            encoding="utf-8",
        )
        expect_failure(checker, python_dependency, "Direktabhängigkeit responses")

        python_port = root / "python-port"
        write_base(source, python_port)
        (python_port / "tests/test_fake.py").write_text(
            "class FakeCrmGateway:\n    pass\n",
            encoding="utf-8",
        )
        expect_failure(checker, python_port, "Testimplementierung eines I/O-Ports")

        frontend = root / "frontend"
        write_base(source, frontend)
        package = json.loads((frontend / "package.json").read_text(encoding="utf-8"))
        package["devDependencies"]["msw"] = "2.10.4"
        (frontend / "package.json").write_text(
            json.dumps(package),
            encoding="utf-8",
        )
        expect_failure(checker, frontend, "Direktabhängigkeit msw")

        browser_response = root / "browser-response"
        write_base(source, browser_response)
        (browser_response / "apps/example.spec.ts").write_text(
            "await page.route('/api/**', async (route) => route.fulfill({}));\n",
            encoding="utf-8",
        )
        expect_failure(checker, browser_response, "Browser-Netzwerkinterception")

        typescript_port = root / "typescript-port"
        write_base(source, typescript_port)
        (typescript_port / "packages/example.test.ts").write_text(
            "class StubDocumentStore {}\n",
            encoding="utf-8",
        )
        expect_failure(
            checker,
            typescript_port,
            "Testimplementierung eines I/O-Ports",
        )

        http_fixture = root / "http-fixture"
        write_base(source, http_fixture)
        fixture = http_fixture / "tests/http-fixtures/response.json"
        fixture.parent.mkdir()
        fixture.write_text('{"status": 200}\n', encoding="utf-8")
        expect_failure(checker, http_fixture, "HTTP-Fixture-Datei")

    print("no-test-doubles-test: OK: sechs negative Policy-Fälle abgewiesen")


if __name__ == "__main__":
    main()
