import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from opsdiary.storage import (
    DATABASE_SCHEMA_VERSION,
    connect,
    init_db,
)


class DatabaseInitializationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "opsdiary.sqlite3"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_schema_version_and_busy_timeout_are_set(self) -> None:
        init_db(self.db_path)
        with connect(self.db_path) as conn:
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], DATABASE_SCHEMA_VERSION)
            self.assertEqual(conn.execute("PRAGMA busy_timeout").fetchone()[0], 10_000)

    def test_initialization_is_atomic_when_seed_fails(self) -> None:
        with patch("opsdiary.storage._seed_synthetic_data", side_effect=RuntimeError("seed failed")):
            with self.assertRaisesRegex(RuntimeError, "seed failed"):
                init_db(self.db_path)

        with connect(self.db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
            self.assertEqual(tables, [])
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)

    def test_newer_schema_is_rejected_before_mutation(self) -> None:
        with connect(self.db_path) as conn:
            conn.execute("PRAGMA user_version = 99")

        with self.assertRaisesRegex(RuntimeError, "newer than this application supports"):
            init_db(self.db_path)

        with connect(self.db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            ).fetchall()
            self.assertEqual(tables, [])
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 99)


if __name__ == "__main__":
    unittest.main()
