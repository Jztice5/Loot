"""Local database configuration tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from loot.persistence.config import load_local_setting


class LocalDatabaseConfigTest(unittest.TestCase):
    """Validate environment precedence and user-file parsing without real secrets."""

    def test_environment_value_takes_precedence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "database.env"
            config_path.write_text(
                "LOOT_TEST_DATABASE_URL=from-file\n",
                encoding="utf-8",
            )
            with patch.dict(
                    os.environ,
                    {"LOOT_TEST_DATABASE_URL": "from-environment"},
            ):
                value = load_local_setting(
                    "LOOT_TEST_DATABASE_URL",
                    config_path=config_path,
                )

        self.assertEqual(value, "from-environment")

    def test_reads_quoted_value_from_user_config(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "database.env"
            config_path.write_text(
                "# local only\nLOOT_TEST_DATABASE_URL='from-file'\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                value = load_local_setting(
                    "LOOT_TEST_DATABASE_URL",
                    config_path=config_path,
                )

        self.assertEqual(value, "from-file")

    def test_missing_setting_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "database.env"
            with patch.dict(os.environ, {}, clear=True):
                value = load_local_setting(
                    "LOOT_TEST_DATABASE_URL",
                    config_path=config_path,
                )

        self.assertIsNone(value)


if __name__ == "__main__":
    unittest.main()
