import tempfile
import unittest
from pathlib import Path

from opsdiary.feedback import summarize_review_feedback
from opsdiary.storage import init_db, save_incident


class ReviewFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "opsdiary.sqlite3"
        init_db(self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_summary_counts_corrections_without_exposing_transcript(self) -> None:
        draft = {
            "transcript": "Synthetic checkout issue.",
            "service_id": "checkout-api",
            "environment": "production",
            "severity": None,
            "symptoms": ["http_5xx"],
            "impact_summary": None,
            "deployment_reference": None,
            "trace_id": "synthetic-trace",
        }
        audit = {
            "candidate_fields": {
                "service_id": "checkout-api",
                "severity": None,
            },
            "confirmed_fields": {
                "service_id": "checkout-api",
                "severity": "SEV2",
            },
            "changed_fields": ["severity"],
        }
        save_incident(draft, db_path=self.db_path, review_audit=audit)

        summary = summarize_review_feedback(self.db_path)

        self.assertEqual(summary["reviewed_incidents"], 1)
        self.assertEqual(summary["fields"]["severity"]["reviewed"], 1)
        self.assertEqual(summary["fields"]["severity"]["corrected"], 1)
        self.assertEqual(summary["fields"]["severity"]["correction_rate"], 1.0)
        self.assertNotIn("transcript", str(summary))


if __name__ == "__main__":
    unittest.main()
