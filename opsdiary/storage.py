"""SQLite persistence and idempotent synthetic dataset seeding."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from opsdiary.settings import DATA_DIR, DATABASE_PATH, PROJECT_ROOT


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect(db_path: Path | str = DATABASE_PATH) -> Iterator[sqlite3.Connection]:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: Path | str = DATABASE_PATH) -> None:
    with connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS services (
                service_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                owner TEXT NOT NULL,
                repository TEXT NOT NULL,
                criticality TEXT NOT NULL,
                aliases_json TEXT NOT NULL DEFAULT '[]'
            );
            CREATE TABLE IF NOT EXISTS deployments (
                deployment_id TEXT PRIMARY KEY,
                service_id TEXT NOT NULL REFERENCES services(service_id),
                environment TEXT NOT NULL,
                version TEXT NOT NULL,
                commit_sha TEXT NOT NULL,
                deployed_at TEXT NOT NULL,
                change_summary TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS incidents (
                incident_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                transcript TEXT NOT NULL,
                service_id TEXT REFERENCES services(service_id),
                environment TEXT,
                severity TEXT,
                symptoms_json TEXT NOT NULL DEFAULT '[]',
                impact_summary TEXT,
                deployment_reference TEXT,
                deployment_id TEXT REFERENCES deployments(deployment_id),
                extraction_json TEXT NOT NULL DEFAULT '{}',
                source TEXT NOT NULL DEFAULT 'local-demo'
            );
            CREATE INDEX IF NOT EXISTS incidents_service_time
                ON incidents(service_id, environment, created_at);
            CREATE INDEX IF NOT EXISTS deployments_service_time
                ON deployments(service_id, environment, deployed_at);
            """
        )
        _seed_synthetic_data(conn)


def _seed_synthetic_data(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT 1 FROM services LIMIT 1").fetchone():
        return

    data_dir = PROJECT_ROOT / "data"
    services = json.loads((data_dir / "seed_services.json").read_text(encoding="utf-8"))
    deployments = json.loads((data_dir / "seed_deployments.json").read_text(encoding="utf-8"))
    incidents = json.loads((data_dir / "seed_incidents.json").read_text(encoding="utf-8"))

    conn.executemany(
        """INSERT INTO services
           (service_id, name, owner, repository, criticality, aliases_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                item["service_id"], item["name"], item["owner"], item["repository"],
                item["criticality"], json.dumps(item["aliases"], ensure_ascii=False),
            )
            for item in services
        ],
    )
    now = utc_now()
    conn.executemany(
        """INSERT INTO deployments
           (deployment_id, service_id, environment, version, commit_sha, deployed_at, change_summary)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        [
            (
                item["deployment_id"], item["service_id"], item["environment"], item["version"],
                item["commit_sha"],
                _iso(now - timedelta(hours=item["hours_ago"])), item["change_summary"],
            )
            for item in deployments
        ],
    )
    conn.executemany(
        """INSERT INTO incidents
           (incident_id, created_at, transcript, service_id, environment, severity,
            symptoms_json, impact_summary, deployment_reference, deployment_id,
            extraction_json, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'synthetic-seed')""",
        [
            (
                item["incident_id"], _iso(now - timedelta(days=item["days_ago"])),
                item["transcript"], item["service_id"], item["environment"], item["severity"],
                json.dumps(item["symptoms"]), item["impact_summary"],
                item.get("deployment_reference"), item.get("deployment_id"),
                json.dumps({"seeded": True}),
            )
            for item in incidents
        ],
    )


def list_services(db_path: Path | str = DATABASE_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM services ORDER BY name").fetchall()
    services = []
    for row in rows:
        item = dict(row)
        item["aliases"] = json.loads(item.pop("aliases_json"))
        services.append(item)
    return services


def list_incidents(limit: int = 50, db_path: Path | str = DATABASE_PATH) -> list[dict]:
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM incidents ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_decode_incident(row) for row in rows]


def get_incident(incident_id: str, db_path: Path | str = DATABASE_PATH) -> dict | None:
    with connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM incidents WHERE incident_id = ?", (incident_id,)
        ).fetchone()
    return _decode_incident(row) if row else None


def _decode_incident(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["symptoms"] = json.loads(item.pop("symptoms_json"))
    item["extraction"] = json.loads(item.pop("extraction_json"))
    return item


def save_incident(
    draft: dict,
    db_path: Path | str = DATABASE_PATH,
    source: str = "local-demo",
) -> str:
    incident_id = f"INC-{uuid4().hex[:8].upper()}"
    created_at = _iso(utc_now())
    service_id = draft.get("service_id")
    environment = draft.get("environment")
    deployment_id = None
    deployment_reference = draft.get("deployment_reference")
    if service_id and environment and deployment_reference:
        with connect(db_path) as conn:
            deployments = conn.execute(
                """SELECT deployment_id, version FROM deployments
                   WHERE service_id = ? AND environment = ?
                   ORDER BY deployed_at DESC""",
                (service_id, environment),
            ).fetchall()
            expected_version = _normalize_version(deployment_reference)
            for deployment in deployments:
                if _normalize_version(deployment["version"]) == expected_version:
                    deployment_id = deployment["deployment_id"]
                    break

    with connect(db_path) as conn:
        conn.execute(
            """INSERT INTO incidents
               (incident_id, created_at, transcript, service_id, environment, severity,
                symptoms_json, impact_summary, deployment_reference, deployment_id,
                extraction_json, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                incident_id, created_at, draft["transcript"], service_id, environment,
                draft.get("severity"), json.dumps(draft.get("symptoms", [])),
                draft.get("impact_summary"), draft.get("deployment_reference"), deployment_id,
                json.dumps(draft, ensure_ascii=False), source,
            ),
        )
    return incident_id


def get_service_enrichment(
    service_id: str | None,
    environment: str | None,
    db_path: Path | str = DATABASE_PATH,
    deployment_reference: str | None = None,
) -> dict | None:
    if not service_id:
        return None
    with connect(db_path) as conn:
        service = conn.execute(
            "SELECT * FROM services WHERE service_id = ?", (service_id,)
        ).fetchone()
        if not service:
            return None
        deployment = None
        referenced_deployment = None
        if environment:
            deployment = conn.execute(
                """SELECT * FROM deployments WHERE service_id = ? AND environment = ?
                   ORDER BY deployed_at DESC LIMIT 1""",
                (service_id, environment),
            ).fetchone()
            if deployment_reference:
                versions = conn.execute(
                    """SELECT * FROM deployments
                       WHERE service_id = ? AND environment = ?
                       ORDER BY deployed_at DESC""",
                    (service_id, environment),
                ).fetchall()
                expected_version = _normalize_version(deployment_reference)
                referenced_deployment = next(
                    (
                        row for row in versions
                        if _normalize_version(row["version"]) == expected_version
                    ),
                    None,
                )
    result = dict(service)
    result["aliases"] = json.loads(result.pop("aliases_json"))
    result["latest_deployment"] = dict(deployment) if deployment else None
    result["deployment_reference"] = deployment_reference
    result["referenced_deployment"] = (
        dict(referenced_deployment) if referenced_deployment else None
    )
    return result


def _normalize_version(value: str) -> str:
    return value.strip().casefold().removeprefix("v")
