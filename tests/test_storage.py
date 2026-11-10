import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from opsdiary.storage import (
    DATABASE_SCHEMA_VERSION,
    add_incident_event,
    connect,
    init_db,
    list_incidents,
    save_incident,
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

    def test_current_schema_skips_seed_and_migration_writes(self) -> None:
        init_db(self.db_path)
        with (
            patch("opsdiary.storage._seed_synthetic_data", side_effect=AssertionError),
            patch("opsdiary.storage._seed_synthetic_runbooks", side_effect=AssertionError),
        ):
            init_db(self.db_path)

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


    def test_concurrent_reads_and_writes_keep_rows_and_ids_unique(self) -> None:
        init_db(self.db_path)
        with connect(self.db_path) as conn:
            initial_incidents = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]

        def save_synthetic_incident(index: int) -> str:
            return save_incident(
                {
                    "transcript": f"Synthetic concurrent load {index}: checkout errors elevated",
                    "service_id": "checkout-api",
                    "environment": "production",
                    "severity": "SEV2",
                    "symptoms": ["elevated_errors"],
                    "impact_summary": f"Synthetic test case {index}",
                    "deployment_reference": "v2.8.1",
                },
                db_path=self.db_path,
            )

        def mixed_operation(index: int):
            if index % 4 == 0:
                return list_incidents(limit=5, db_path=self.db_path)
            return save_synthetic_incident(index)

        with ThreadPoolExecutor(max_workers=12) as pool:
            mixed_results = list(pool.map(mixed_operation, range(120)))

        incident_ids = [result for result in mixed_results if isinstance(result, str)]
        self.assertEqual(len(incident_ids), 90)
        self.assertEqual(len(set(incident_ids)), len(incident_ids))
        self.assertTrue(all(item.startswith("INC-") and len(item) == 36 for item in incident_ids))

        def add_synthetic_event(index: int) -> str:
            return add_incident_event(
                incident_ids[0],
                "update",
                f"Synthetic concurrent update {index}",
                "local-demo",
                "load-check",
                db_path=self.db_path,
            )

        with ThreadPoolExecutor(max_workers=12) as pool:
            event_ids = list(pool.map(add_synthetic_event, range(len(incident_ids))))

        self.assertEqual(len(set(event_ids)), len(event_ids))
        self.assertTrue(all(item.startswith("EVT-") and len(item) == 36 for item in event_ids))
        with connect(self.db_path) as conn:
            incident_count = conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0]
            event_count = conn.execute("SELECT COUNT(*) FROM incident_events").fetchone()[0]
        self.assertEqual(incident_count, initial_incidents + len(incident_ids))
        self.assertEqual(event_count, len(event_ids))


if __name__ == "__main__":
    unittest.main()
