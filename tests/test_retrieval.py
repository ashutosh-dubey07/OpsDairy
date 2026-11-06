import tempfile
import unittest
from pathlib import Path

from opsdiary.retrieval import retrieve_incidents
from opsdiary.storage import init_db


class IncidentRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "opsdiary.sqlite3"
        init_db(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fts_returns_cited_records_and_respects_metadata_filters(self) -> None:
        matches = retrieve_incidents(
            "Checkout production 5xx errors payments fail",
            service_id="checkout-api",
            environment="production",
            limit=5,
            db_path=self.db_path,
        )

        ids = {item["incident_id"] for item in matches}
        self.assertIn("SYN-1041", ids)
        self.assertTrue(all(item["matched_terms"] for item in matches))
        self.assertTrue(all(item["evidence_excerpt"] for item in matches))
        self.assertTrue(all(item["method"] == "sqlite-fts5-lexical" for item in matches))

        wrong_service = retrieve_incidents(
            "login 401 errors",
            service_id="checkout-api",
            environment="production",
            db_path=self.db_path,
        )
        self.assertEqual(wrong_service, [])

    def test_stop_words_only_query_returns_no_results(self) -> None:
        self.assertEqual(
            retrieve_incidents("the issue is in service", db_path=self.db_path), []
        )


if __name__ == "__main__":
    unittest.main()
