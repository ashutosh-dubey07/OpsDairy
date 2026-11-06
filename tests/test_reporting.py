import unittest

from opsdiary.reporting import build_incident_report


class IncidentReportTests(unittest.TestCase):
    def test_report_includes_confirmed_fields_and_match_evidence(self) -> None:
        incident = {
            "incident_id": "INC-1234",
            "created_at": "2026-11-06T12:00:00+00:00",
            "source": "local-demo",
            "service_id": "checkout-api",
            "environment": "production",
            "severity": "SEV2",
            "symptoms": ["http_5xx"],
            "impact_summary": "Some checkouts failed.",
            "deployment_reference": "v2.8.1",
            "transcript": "Checkout had 5xx errors.",
        }
        service = {
            "name": "Checkout API",
            "owner": "Payments Platform",
            "criticality": "Tier 1",
            "repository": "synthetic/checkout-api",
            "latest_deployment": None,
        }
        patterns = {
            "lookback_days": 30,
            "matches": [
                {
                    "incident_id": "SYN-1001",
                    "created_at": "2026-11-04T12:00:00+00:00",
                    "matched_symptoms": ["http_5xx"],
                    "transcript": "Earlier checkout had 5xx errors.",
                    "deployment_id": "DEP-CHK-281",
                }
            ],
        }

        report = build_incident_report(incident, service, patterns)

        self.assertIn("# Incident INC-1234", report)
        self.assertIn("HTTP 5xx / server errors", report)
        self.assertIn("SYN-1001", report)
        self.assertIn("Earlier checkout had 5xx errors.", report)
        self.assertIn("historical matches, not a prediction", report)


if __name__ == "__main__":
    unittest.main()
