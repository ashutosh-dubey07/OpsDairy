import sqlite3
import tempfile
import unittest
from pathlib import Path

from opsdiary.retrieval import retrieve_incidents, retrieve_runbooks
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

    def test_runbook_seed_and_search_index_are_idempotent(self) -> None:
        init_db(self.db_path)
        conn = sqlite3.connect(self.db_path)
        try:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runbooks").fetchone()[0], 8)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM runbook_search").fetchone()[0], 8)
        finally:
            conn.close()

    def test_runbooks_require_confirmed_service_and_return_match_evidence(self) -> None:
        matches = retrieve_runbooks(
            "Checkout production 5xx errors slow payments fail",
            service_id="checkout-api",
            environment="production",
            symptoms=["http_5xx", "payment_failures"],
            db_path=self.db_path,
        )
        self.assertTrue(matches)
        self.assertEqual(matches[0]["runbook_id"], "SYN-RB-CHK-5XX")
        self.assertTrue(matches[0]["matched_terms"])
        self.assertTrue(matches[0]["matched_symptoms"])
        self.assertEqual(matches[0]["source"], "synthetic-runbook")

        wrong_service = retrieve_runbooks(
            "Checkout production 5xx errors slow payments fail",
            service_id="auth-api",
            environment="production",
            symptoms=["http_5xx", "payment_failures"],
            db_path=self.db_path,
        )
        self.assertEqual(wrong_service, [])
        self.assertEqual(
            retrieve_runbooks("5xx errors", service_id=None, db_path=self.db_path), []
        )

    def test_catalog_db_pool_runbook_retrieval(self) -> None:
        matches = retrieve_runbooks(
            "Catalog API production connection pool exhausted too many connections",
            service_id="catalog-api",
            environment="production",
            symptoms=["db_pool_exhaustion"],
            db_path=self.db_path,
        )
        self.assertTrue(matches)
        self.assertEqual(matches[0]["runbook_id"], "SYN-RB-CAT-DB")
        self.assertIn("db_pool_exhaustion", matches[0]["matched_symptoms"])


if __name__ == "__main__":
    unittest.main()
