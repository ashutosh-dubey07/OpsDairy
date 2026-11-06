"""Offline extraction quality gate using synthetic Hinglish incident cases."""

import json
import sys

from opsdiary.extraction import extract_incident
from opsdiary.settings import DATA_DIR

SERVICES_PATH = DATA_DIR / "seed_services.json"
CASES_PATH = DATA_DIR / "evaluation_cases.json"
FIELDS = ("service_id", "environment", "severity", "symptoms", "deployment_reference")
EVIDENCE_FIELDS = {
    "service_id": "service_id",
    "environment": "environment",
    "severity": "severity",
    "symptoms": "symptoms",
    "deployment_reference": "deployment_reference",
}
MINIMUM_ACCURACY = 0.9
MINIMUM_EVIDENCE_COVERAGE = 0.95


def evaluate() -> dict:
    services = json.loads(SERVICES_PATH.read_text(encoding="utf-8"))
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    correct = {field: 0 for field in FIELDS}
    evidence_expected = 0
    evidence_found = 0
    failures = []

    for case in cases:
        draft = extract_incident(case["transcript"], services)
        actual = draft.model_dump(mode="json")
        expected = case["expected"]
        case_failures = []

        for field in FIELDS:
            actual_value = sorted(actual[field]) if field == "symptoms" else actual[field]
            expected_value = sorted(expected[field]) if field == "symptoms" else expected[field]
            if actual_value == expected_value:
                correct[field] += 1
            else:
                case_failures.append(
                    {"field": field, "expected": expected_value, "actual": actual_value}
                )

            is_present = bool(expected[field]) if field == "symptoms" else expected[field] is not None
            if is_present:
                evidence_expected += 1
                evidence_key = EVIDENCE_FIELDS[field]
                if actual.get("evidence", {}).get(evidence_key):
                    evidence_found += 1

        if case_failures:
            failures.append({"case_id": case["case_id"], "mismatches": case_failures})

    total = len(cases)
    metrics = {f"{field}_accuracy": correct[field] / total for field in FIELDS}
    metrics["evidence_coverage"] = (
        evidence_found / evidence_expected if evidence_expected else 1.0
    )
    thresholds = {
        **{f"{field}_accuracy": MINIMUM_ACCURACY for field in FIELDS},
        "evidence_coverage": MINIMUM_EVIDENCE_COVERAGE,
    }
    failed_gates = [
        name for name, minimum in thresholds.items() if metrics[name] < minimum
    ]
    return {
        "cases": total,
        "metrics": metrics,
        "thresholds": thresholds,
        "failed_gates": failed_gates,
        "case_mismatches": failures,
        "passed": not failed_gates,
    }


def main() -> int:
    result = evaluate()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
