from pathlib import Path


def test_planned_repository_roots_exist() -> None:
    root = Path(__file__).resolve().parents[2]
    expected = (
        "apps/api",
        "apps/worker",
        "apps/web",
        "apps/pwa",
        "apps/public",
        "packages/ui",
        "packages/features",
        "packages/api-client",
        "packages/testkit",
        "src/leonaid/domain",
        "src/leonaid/application",
        "src/leonaid/adapters/postgres",
        "src/leonaid/adapters/twenty",
        "src/leonaid/adapters/storage",
        "src/leonaid/adapters/mail",
        "src/leonaid/adapters/typst",
        "src/leonaid/entrypoints/fastapi",
        "src/leonaid/entrypoints/worker",
        "infra/compose",
        "infra/twenty",
        "infra/rustfs",
        "infra/proxy",
        "infra/backup",
        "tests/integration",
        "tests/contract",
        "tests/e2e",
        "tests/fixtures/golden/v1",
    )
    missing = [relative for relative in expected if not (root / relative).is_dir()]
    assert missing == []
