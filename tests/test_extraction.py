import json
import unittest

from opsdiary.extraction import extract_incident
from opsdiary.settings import DATA_DIR


SERVICES = json.loads((DATA_DIR / "seed_services.json").read_text(encoding="utf-8"))


class ConservativeExtractionTests(unittest.TestCase):
    def test_negated_server_errors_are_not_active_symptoms(self) -> None:
        draft = extract_incident(
            "Checkout API production mein 5xx errors nahi aa rahe.", SERVICES
        )

        self.assertEqual(draft.symptoms, [])
        self.assertEqual(draft.environment, "production")

    def test_normal_latency_is_not_an_active_symptom(self) -> None:
        draft = extract_incident(
            "Search API staging mein latency normal hai after cache warmup.", SERVICES
        )

        self.assertEqual(draft.symptoms, [])

    def test_positive_auth_error_survives_nearby_negated_login_phrase(self) -> None:
        draft = extract_incident(
            "Auth API staging mein login failures nahi hain, par 401 errors aa rahe hain.",
            SERVICES,
        )

        self.assertEqual(draft.symptoms, ["auth_failures"])

    def test_corrected_severity_and_environment_skip_negated_values(self) -> None:
        severity = extract_incident(
            "Auth API production incident not P1, confirmed P2; no 401 errors.", SERVICES
        )
        environment = extract_incident(
            "Checkout API is not staging; production requests time out.", SERVICES
        )

        self.assertEqual(severity.severity, "SEV2")
        self.assertEqual(severity.symptoms, [])
        self.assertEqual(environment.environment, "production")
        self.assertEqual(environment.symptoms, ["timeouts"])

    def test_deployment_reference_uses_active_version_after_correction(self) -> None:
        draft = extract_incident(
            "Checkout API production mein deployment v2.8.1 is not deployed; "
            "release v2.8.2 caused latency.",
            SERVICES,
        )

        self.assertEqual(draft.deployment_reference, "v2.8.2")
        self.assertIn("v2.8.2", draft.evidence["deployment_reference"])

    def test_production_context_remains_valid_when_symptom_is_negated(self) -> None:
        draft = extract_incident(
            "Checkout API production is not responding; 5xx errors are present.", SERVICES
        )

        self.assertEqual(draft.environment, "production")
        self.assertEqual(draft.symptoms, ["http_5xx"])

    def test_impact_extracts_the_customer_effect_clause(self) -> None:
        draft = extract_incident(
            "Checkout API production mein deploy v2.8.1 ke baad 5xx errors aa rahe hain "
            "aur checkout slow chal raha hai; kuch users payments complete nahi paa rahe.",
            SERVICES,
        )

        self.assertEqual(draft.impact_summary, "kuch users payments complete nahi paa rahe.")


if __name__ == "__main__":
    unittest.main()
