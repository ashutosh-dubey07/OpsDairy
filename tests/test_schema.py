import unittest

from pydantic import ValidationError

from opsdiary.schema import IncidentDraft


class IncidentDraftValidationTests(unittest.TestCase):
    def test_accepts_supported_incident_fields(self) -> None:
        draft = IncidentDraft(
            transcript="Checkout API latency increased after deploy.",
            service_id="checkout-api",
            symptoms=["high_latency"],
            impact_summary="Checkout requests are slow.",
            deployment_reference="v2.8.1",
            evidence={"service_id": "Checkout API"},
        )

        self.assertEqual(draft.service_id, "checkout-api")

    def test_rejects_excessive_symptom_count(self) -> None:
        with self.assertRaises(ValidationError):
            IncidentDraft(transcript="A" * 20, symptoms=[f"symptom-{i}" for i in range(21)])

    def test_rejects_excessive_evidence_field_count(self) -> None:
        with self.assertRaises(ValidationError):
            IncidentDraft(
                transcript="A" * 20,
                evidence={f"field-{i}": "evidence" for i in range(21)},
            )

    def test_rejects_overlong_impact_summary(self) -> None:
        with self.assertRaises(ValidationError):
            IncidentDraft(transcript="A" * 20, impact_summary="x" * 2001)


if __name__ == "__main__":
    unittest.main()
