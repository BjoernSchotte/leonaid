from pathlib import Path

from tools.seed.golden import SeedError
from tools.twenty.provision import apply_with_metadata_retry


def test_apply_retries_transient_twenty_metadata_race(monkeypatch) -> None:
    class StubProvisioner:
        calls = 0

        def apply(self, token_output: Path | None) -> dict[str, object]:
            self.calls += 1
            if self.calls < 3:
                raise SeedError("Twenty GraphQL: Could not find flat entity in maps")
            return {"schemaVersion": 1}

    provisioner = StubProvisioner()
    monkeypatch.setattr("tools.twenty.provision.time.sleep", lambda _: None)

    assert apply_with_metadata_retry(provisioner, None) == {"schemaVersion": 1}
    assert provisioner.calls == 3
