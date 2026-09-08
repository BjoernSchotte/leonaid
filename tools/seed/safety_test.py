"""Verify isolated test names do not weaken destructive reset target checks."""

import copy
from pathlib import Path
import sys
from typing import Any
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.seed.safety import ResetSafetyError, validate


class ResetSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.project = "leonaid-poc012-test-833458328-12345"
        self.environment = {"LEONAID_ENV": "local", "LEONAID_RESET_ALLOWED": "true"}
        self.config: dict[str, Any] = {
            "name": self.project,
            "services": {
                "api": {
                    "environment": {
                        "CORE_DATABASE_URL": "postgresql://fixture@core-postgres:5432/leonaid",
                        "TWENTY_BASE_URL": "http://twenty-server:3000",
                        "RUSTFS_ENDPOINT_URL": "http://rustfs:9000",
                        "MAIL_HEALTH_URL": "http://mailpit:8025",
                    }
                },
                "twenty-server": {
                    "environment": {
                        "PG_DATABASE_URL": "postgresql://fixture@twenty-postgres:5432/default",
                    }
                },
                "core-postgres": {},
                "mailpit": {},
                "rustfs": {},
                "twenty-postgres": {},
            },
            "volumes": {"core-postgres-data": {}},
        }

    def test_existing_and_isolated_local_names(self) -> None:
        for name in ("leonaid", "leonaid-poc012-test", self.project):
            with self.subTest(name=name):
                config = copy.deepcopy(self.config)
                config["name"] = name
                validate(config, project_name=name, env_values=self.environment)

    def test_arbitrary_or_production_names_remain_rejected(self) -> None:
        for name in (
            "leonaid-production",
            "leonaid-staging",
            "leonaid-1-2",
            "leonaid-poc012-test-production",
            "leonaid-poc012-test-123",
            "leonaid-poc012-test-123-abc",
            "leonaid-poc012-test-123-456-extra",
            self.project + "\n",
            "another-project",
        ):
            with self.subTest(name=name):
                config = copy.deepcopy(self.config)
                config["name"] = name
                with self.assertRaises(ResetSafetyError):
                    validate(config, project_name=name, env_values=self.environment)

    def test_unique_name_still_requires_every_target_boundary(self) -> None:
        variants = []
        for service, key, bad in (
            (
                "api",
                "CORE_DATABASE_URL",
                "postgresql://fixture@production.example:5432/db",
            ),
            ("api", "TWENTY_BASE_URL", "http://production.example:3000"),
            ("api", "RUSTFS_ENDPOINT_URL", "http://production.example:9000"),
            ("api", "MAIL_HEALTH_URL", "http://production.example:8025"),
            (
                "twenty-server",
                "PG_DATABASE_URL",
                "postgresql://fixture@production.example:5432/db",
            ),
        ):
            config = copy.deepcopy(self.config)
            config["services"][service]["environment"][key] = bad
            variants.append((config, self.environment))
        config = copy.deepcopy(self.config)
        config["name"] = "leonaid"
        variants.append((config, self.environment))
        config = copy.deepcopy(self.config)
        config["volumes"]["core-postgres-data"] = {"external": True}
        variants.append((config, self.environment))
        config = copy.deepcopy(self.config)
        del config["services"]["core-postgres"]
        variants.append((config, self.environment))
        variants.extend(
            (self.config, env)
            for env in (
                {"LEONAID_ENV": "production", "LEONAID_RESET_ALLOWED": "true"},
                {"LEONAID_ENV": "local", "LEONAID_RESET_ALLOWED": "false"},
            )
        )
        for index, (config, environment) in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(ResetSafetyError):
                validate(config, project_name=self.project, env_values=environment)


if __name__ == "__main__":
    unittest.main()
