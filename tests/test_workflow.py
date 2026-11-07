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
        self.assertEqual(
            analysis.incident["extraction"]["review_audit"]["changed_fields"], []
        )
        self.assertEqual(analysis.incident["deployment_id"], "DEP-CHK-281")
        self.assertEqual(analysis.service_context["name"], "Checkout API")
        self.assertTrue(analysis.runbook_references)
        self.assertEqual(analysis.runbook_references[0]["runbook_id"], "SYN-RB-CHK-5XX")
        self.assertIn("Synthetic runbook references", analysis.report)
        self.assertIn("SYN-RB-CHK-5XX", analysis.report)
        self.assertEqual(
            analysis.service_context["referenced_deployment"]["deployment_id"],
            "DEP-CHK-281",
        )
        self.assertIn("Checkout API mein production incident report hua.", analysis.summary)
        self.assertIn(f"# Incident {incident_id}", analysis.report)

    def test_older_transcript_version_matches_older_deployment_not_latest(self) -> None:
        draft = IncidentDraft(
            transcript="Checkout production mein v2.8.0 ke saath synthetic incident hua.",
            service_id="checkout-api",
            environment="production",
            deployment_reference="v2.8.0",
        )

        incident_id = self.workflow.save_reviewed(draft, source="local-demo")
        analysis = self.workflow.analyze(incident_id)

        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertEqual(analysis.incident["deployment_id"], "DEP-CHK-280")
        self.assertEqual(
            analysis.service_context["referenced_deployment"]["deployment_id"],
            "DEP-CHK-280",
        )
        self.assertEqual(
            analysis.service_context["latest_deployment"]["deployment_id"],
            "DEP-CHK-281",
        )
        self.assertIn("Latest catalog deployment (context only)", analysis.report)

    def test_unmatched_transcript_version_is_not_linked_to_latest(self) -> None:
        draft = IncidentDraft(
            transcript="Checkout production mein v9.9.9 ke baad synthetic issue hua.",
            service_id="checkout-api",
            environment="production",
            deployment_reference="v9.9.9",
        )

        incident_id = self.workflow.save_reviewed(draft, source="local-demo")
        analysis = self.workflow.analyze(incident_id)

        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertIsNone(analysis.incident["deployment_id"])
        self.assertIsNone(analysis.service_context["referenced_deployment"])
        self.assertEqual(
            analysis.service_context["latest_deployment"]["deployment_id"],
            "DEP-CHK-281",
        )
        self.assertIn("no exact deployment version matched", analysis.report)

    def test_analysis_includes_lexical_history_with_source_evidence(self) -> None:
        draft = IncidentDraft(
            transcript="Checkout production checkout complete flow is degraded after a synthetic change.",
            service_id="checkout-api",
            environment="production",
        )

        incident_id = self.workflow.save_reviewed(draft, source="local-demo")
        analysis = self.workflow.analyze(incident_id)

        self.assertIsNotNone(analysis)
        assert analysis is not None
        self.assertTrue(analysis.related_records)
        self.assertTrue(
            all(record["incident_id"].startswith("SYN-") for record in analysis.related_records)
        )
        self.assertTrue(all(record["evidence_excerpt"] for record in analysis.related_records))
        self.assertIn("Additional transcript search evidence", analysis.report)

    def test_operator_field_corrections_are_saved_as_review_evidence(self) -> None:
        candidate = self.workflow.extract_candidate(SAMPLE_TRANSCRIPT)
        reviewed = candidate.model_copy(update={"severity": "SEV2"})

        incident_id = self.workflow.save_reviewed(
            reviewed, source="local-demo", candidate_data=candidate
        )
        incident = self.workflow.analyze(incident_id)

        self.assertIsNotNone(incident)
        assert incident is not None
        audit = incident.incident["extraction"]["review_audit"]
        self.assertEqual(audit["candidate_fields"]["severity"], None)
        self.assertEqual(audit["confirmed_fields"]["severity"], "SEV2")
        self.assertEqual(audit["changed_fields"], ["severity"])
        self.assertIn("severity: not set -> SEV2", incident.report)

    def test_unknown_service_is_rejected_before_persistence(self) -> None:
        draft = IncidentDraft(transcript="Synthetic incident", service_id="unknown-service")

        with self.assertRaisesRegex(ValueError, "Unknown service"):
            self.workflow.save_reviewed(draft, source="local-demo")


if __name__ == "__main__":
    unittest.main()
