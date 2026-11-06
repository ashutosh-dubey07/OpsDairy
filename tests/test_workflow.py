import tempfile
import unittest
from pathlib import Path

from opsdiary.schema import IncidentDraft
from opsdiary.storage import init_db, list_services
from opsdiary.workflow import IncidentWorkflow


SAMPLE_TRANSCRIPT = (
    "Checkout API production mein deploy v2.8.1 ke baad 5xx errors aa rahe hain "
    "aur checkout slow chal raha hai; kuch users payments complete nahi paa rahe."
)


class IncidentWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "opsdiary.sqlite3"
        init_db(self.db_path)
        self.workflow = IncidentWorkflow(list_services(self.db_path), db_path=self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_reviewed_incident_can_be_saved_and_analyzed(self) -> None:
        candidate = self.workflow.extract_candidate(SAMPLE_TRANSCRIPT)
        candidate.severity = "SEV2"

        incident_id = self.workflow.save_reviewed(candidate, source="local-demo")
        analysis = self.workflow.analyze(incident_id)

        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertEqual(analysis.incident["severity"], "SEV2")
        self.assertEqual(analysis.service_context["name"], "Checkout API")
        self.assertIn("Checkout API mein production incident report hua.", analysis.summary)
        self.assertIn(f"# Incident {incident_id}", analysis.report)

    def test_unknown_service_is_rejected_before_persistence(self) -> None:
        draft = IncidentDraft(transcript="Synthetic incident", service_id="unknown-service")

        with self.assertRaisesRegex(ValueError, "Unknown service"):
            self.workflow.save_reviewed(draft, source="local-demo")


if __name__ == "__main__":
    unittest.main()
