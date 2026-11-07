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

            CREATE VIRTUAL TABLE IF NOT EXISTS incident_search USING fts5(
                incident_id UNINDEXED,
                transcript,
                impact_summary,
                service_id UNINDEXED,
                environment UNINDEXED,
                symptoms
            );

            CREATE TABLE IF NOT EXISTS runbooks (
                runbook_id TEXT PRIMARY KEY,
                service_id TEXT NOT NULL REFERENCES services(service_id),
                title TEXT NOT NULL,
                version TEXT NOT NULL,
                environment TEXT,
                symptoms_json TEXT NOT NULL DEFAULT '[]',
                keywords TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'synthetic-runbook'
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS runbook_search USING fts5(
                runbook_id UNINDEXED,
                title,
                body,
                keywords,
                service_id UNINDEXED,
                environment UNINDEXED
            );

            CREATE TRIGGER IF NOT EXISTS runbooks_search_insert
            AFTER INSERT ON runbooks BEGIN
                INSERT INTO runbook_search
                    (runbook_id, title, body, keywords, service_id, environment)
                VALUES (
                    new.runbook_id, new.title, new.body, new.keywords,
                    new.service_id, COALESCE(new.environment, '')
                );
            END;

            CREATE TRIGGER IF NOT EXISTS runbooks_search_update
            AFTER UPDATE ON runbooks BEGIN
                DELETE FROM runbook_search WHERE runbook_id = old.runbook_id;
                INSERT INTO runbook_search
                    (runbook_id, title, body, keywords, service_id, environment)
                VALUES (
                    new.runbook_id, new.title, new.body, new.keywords,
                    new.service_id, COALESCE(new.environment, '')
                );
            END;

            CREATE TRIGGER IF NOT EXISTS runbooks_search_delete
            AFTER DELETE ON runbooks BEGIN
                DELETE FROM runbook_search WHERE runbook_id = old.runbook_id;
            END;

            CREATE TRIGGER IF NOT EXISTS incidents_search_insert
            AFTER INSERT ON incidents BEGIN
                INSERT INTO incident_search
                    (incident_id, transcript, impact_summary, service_id, environment, symptoms)
                VALUES (
                    new.incident_id, new.transcript, COALESCE(new.impact_summary, ''),
                    COALESCE(new.service_id, ''), COALESCE(new.environment, ''), new.symptoms_json
                );
            END;

            CREATE TRIGGER IF NOT EXISTS incidents_search_update
            AFTER UPDATE ON incidents BEGIN
                DELETE FROM incident_search WHERE incident_id = old.incident_id;
                INSERT INTO incident_search
                    (incident_id, transcript, impact_summary, service_id, environment, symptoms)
                VALUES (
                    new.incident_id, new.transcript, COALESCE(new.impact_summary, ''),
                    COALESCE(new.service_id, ''), COALESCE(new.environment, ''), new.symptoms_json
                );
            END;

            CREATE TRIGGER IF NOT EXISTS incidents_search_delete
            AFTER DELETE ON incidents BEGIN
                DELETE FROM incident_search WHERE incident_id = old.incident_id;
            END;
            """
        )
        _seed_synthetic_data(conn)
        _seed_synthetic_runbooks(conn)
        _backfill_incident_search(conn)
        _backfill_runbook_search(conn)


def _backfill_incident_search(conn: sqlite3.Connection) -> None:
    """Index existing local records when upgrading a database created by an older version."""
    missing = conn.execute(
        """SELECT i.incident_id, i.transcript, i.impact_summary, i.service_id,
                  i.environment, i.symptoms_json
           FROM incidents AS i
           LEFT JOIN incident_search AS s ON s.incident_id = i.incident_id
           WHERE s.incident_id IS NULL"""
    ).fetchall()
    if not missing:
        return
    conn.executemany(
        """INSERT INTO incident_search
           (incident_id, transcript, impact_summary, service_id, environment, symptoms)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                row["incident_id"], row["transcript"], row["impact_summary"] or "",
                row["service_id"] or "", row["environment"] or "", row["symptoms_json"],
            )
            for row in missing
        ],
    )


def _backfill_runbook_search(conn: sqlite3.Connection) -> None:
    missing = conn.execute(
        """SELECT r.runbook_id, r.title, r.body, r.keywords, r.service_id, r.environment
           FROM runbooks AS r
           LEFT JOIN runbook_search AS s ON s.runbook_id = r.runbook_id
           WHERE s.runbook_id IS NULL"""
    ).fetchall()
    if not missing:
        return
    conn.executemany(
        """INSERT INTO runbook_search
           (runbook_id, title, body, keywords, service_id, environment)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                row["runbook_id"], row["title"], row["body"], row["keywords"],
                row["service_id"], row["environment"] or "",
            )
            for row in missing
        ],
    )


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


def _seed_synthetic_runbooks(conn: sqlite3.Connection) -> None:
    data_path = PROJECT_ROOT / "data" / "seed_runbooks.json"
    runbooks = json.loads(data_path.read_text(encoding="utf-8"))
    conn.executemany(
        """INSERT INTO runbooks
           (runbook_id, service_id, title, version, environment, symptoms_json,
            keywords, body, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'synthetic-runbook')
           ON CONFLICT(runbook_id) DO UPDATE SET
               service_id = excluded.service_id,
               title = excluded.title,
               version = excluded.version,
               environment = excluded.environment,
               symptoms_json = excluded.symptoms_json,
               keywords = excluded.keywords,
               body = excluded.body,
               source = excluded.source
           WHERE runbooks.service_id IS NOT excluded.service_id
              OR runbooks.title IS NOT excluded.title
              OR runbooks.version IS NOT excluded.version
              OR runbooks.environment IS NOT excluded.environment
              OR runbooks.symptoms_json IS NOT excluded.symptoms_json
              OR runbooks.keywords IS NOT excluded.keywords
              OR runbooks.body IS NOT excluded.body
              OR runbooks.source IS NOT excluded.source""",
        [
            (
                item["runbook_id"], item["service_id"], item["title"], item["version"],
                item.get("environment"), json.dumps(item.get("symptoms", [])),
                item["keywords"], item["body"],
            )
            for item in runbooks
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


def list_review_audits(db_path: Path | str = DATABASE_PATH) -> list[dict]:
    """Return only field-review metadata, without copying transcript content."""
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT source, extraction_json FROM incidents ORDER BY created_at"
        ).fetchall()
    audits = []
    for row in rows:
        extraction = json.loads(row["extraction_json"])
        if audit := extraction.get("review_audit"):
            audits.append({"source": row["source"], **audit})
    return audits


def _decode_incident(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["symptoms"] = json.loads(item.pop("symptoms_json"))
    item["extraction"] = json.loads(item.pop("extraction_json"))
    return item


def save_incident(
    draft: dict,
    db_path: Path | str = DATABASE_PATH,
    source: str = "local-demo",
    review_audit: dict | None = None,
) -> str:
    incident_id = f"INC-{uuid4().hex[:8].upper()}"
    created_at = _iso(utc_now())
    service_id = draft.get("service_id")
    environment = draft.get("environment")
    deployment_id = None
    deployment_reference = draft.get("deployment_reference")
    extraction = dict(draft)
    if review_audit is not None:
        extraction["review_audit"] = {**review_audit, "saved_at": created_at}
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
                json.dumps(extraction, ensure_ascii=False), source,
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
