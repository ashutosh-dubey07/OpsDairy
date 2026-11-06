"""Evidence-backed deterministic matching against prior saved incidents."""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from opsdiary.settings import DATABASE_PATH
from opsdiary.storage import connect


def detect_patterns(
    service_id: str | None,
    environment: str | None,
    symptoms: list[str],
    as_of: str | None = None,
    lookback_days: int = 30,
    db_path: Path | str = DATABASE_PATH,
) -> dict:
    """Match exact service/environment plus at least one shared symptom tag."""
    if not service_id or not environment or not symptoms:
        return {"matches": [], "repeated": False, "lookback_days": lookback_days}

    try:
        end = datetime.fromisoformat(as_of) if as_of else datetime.now(timezone.utc)
    except ValueError:
        end = datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    cutoff = (end - timedelta(days=lookback_days)).astimezone(timezone.utc).isoformat(timespec="seconds")
    end_text = end.astimezone(timezone.utc).isoformat(timespec="seconds")

    with connect(db_path) as conn:
        rows = conn.execute(
            """SELECT incident_id, created_at, transcript, symptoms_json, deployment_id
               FROM incidents
               WHERE service_id = ? AND environment = ?
                 AND created_at >= ? AND created_at < ?
               ORDER BY created_at DESC""",
            (service_id, environment, cutoff, end_text),
        ).fetchall()

    current_tags = set(symptoms)
    matches = []
    for row in rows:
        prior_tags = set(json.loads(row["symptoms_json"]))
        shared = sorted(current_tags & prior_tags)
        if not shared:
            continue
        matches.append(
            {
                "incident_id": row["incident_id"],
                "created_at": row["created_at"],
                "transcript": row["transcript"],
                "matched_symptoms": shared,
                "deployment_id": row["deployment_id"],
            }
        )
    return {
        "matches": matches,
        "repeated": len(matches) >= 2,
        "lookback_days": lookback_days,
    }
