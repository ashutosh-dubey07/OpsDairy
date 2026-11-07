import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from opsdiary.settings import DATA_DIR, PROJECT_ROOT, resolve_database_path


class DatabasePathSettingsTests(unittest.TestCase):
    def test_default_path_uses_project_data_directory(self) -> None:
        self.assertEqual(resolve_database_path(""), DATA_DIR / "opsdiary.sqlite3")

    def test_relative_path_resolves_from_project_root(self) -> None:
        self.assertEqual(
            resolve_database_path("runtime/opsdiary.sqlite3"),
            (PROJECT_ROOT / "runtime" / "opsdiary.sqlite3").resolve(),
        )

    def test_absolute_path_is_preserved(self) -> None:
        with TemporaryDirectory() as directory:
            expected = Path(directory) / "opsdiary.sqlite3"
            self.assertEqual(resolve_database_path(str(expected)), expected.resolve())

    def test_database_path_reads_environment_configuration(self) -> None:
        with patch.dict(os.environ, {"OPSDIARY_DATABASE_PATH": "runtime/custom.sqlite3"}):
            self.assertEqual(
                resolve_database_path(),
                (PROJECT_ROOT / "runtime" / "custom.sqlite3").resolve(),
            )


if __name__ == "__main__":
    unittest.main()
