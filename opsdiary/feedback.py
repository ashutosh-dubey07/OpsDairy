"""Summarize operator correction signals for local extractor evaluation."""

import json
from pathlib import Path

from opsdiary.settings import DATABASE_PATH
from opsdiary.storage import list_review_audits


REVIEW_FIELDS = (
    "service_id",
    "environment",
    "severity",
    "symptoms",
    "impact_summary",
    "deployment_reference",
)


def summarize_review_feedback(db_path: Path | str = DATABASE_PATH) -> dict:
    audits = list_review_audits(db_path)
    field_metrics = {}
    for field_name in REVIEW_FIELDS:
        reviewed_count = sum(
            field_name in audit.get("candidate_fields", {})
            and field_name in audit.get("confirmed_fields", {})
            for audit in audits
        )
        corrected_count = sum(
            field_name in audit.get("changed_fields", []) for audit in audits
        )
        field_metrics[field_name] = {
            "reviewed": reviewed_count,
            "corrected": corrected_count,
            "correction_rate": round(corrected_count / reviewed_count, 4)
            if reviewed_count
            else None,
        }
    return {
        "reviewed_incidents": len(audits),
        "interpretation": "Correction rates are review signals, not field accuracy metrics.",
        "fields": field_metrics,
    }


def main() -> None:
    print(json.dumps(summarize_review_feedback(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
