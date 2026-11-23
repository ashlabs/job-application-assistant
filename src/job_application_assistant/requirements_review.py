"""Explicit requirements corrections with source checks and revision history."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

from job_application_assistant.job_capture_storage import load_capture
from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.job_requirements_storage import load_requirements
from job_application_assistant.job_requirements_validation import validate_requirements
from job_application_assistant.profile_match_validation import requirements_revision


class RequirementsReviewConflict(ValueError):
    """Another review changed the extraction before this save."""


def duplicate_requirement_ids(requirements: JobRequirements) -> list[list[str]]:
    """Flag equal descriptions after case and whitespace normalization."""
    groups = {}
    for item in requirements.requirements:
        key = " ".join(item.description.split()).casefold().rstrip(".;")
        groups.setdefault(key, []).append(str(item.requirement_uuid))
    return [ids for ids in groups.values() if len(ids) > 1]


def review_snapshot(database: Path, capture_uuid: UUID) -> dict:
    """Read the current extraction without invoking a model."""
    requirements = load_requirements(database, capture_uuid)
    if requirements is None:
        raise RequirementsReviewConflict("Extract this job's requirements first.")
    return {
        "requirements": requirements.model_dump(mode="json"),
        "revision": requirements_revision(requirements),
        "duplicate_groups": duplicate_requirement_ids(requirements),
    }


def save_requirements_review(
    database: Path,
    capture_uuid: UUID,
    expected_revision: str,
    proposed: JobRequirements,
) -> dict:
    """Atomically compare, archive, and replace; identical retries are safe."""
    capture = load_capture(database, capture_uuid)
    if proposed.capture_uuid != capture_uuid:
        raise ValueError("The correction references a different capture.")
    validated = validate_requirements(capture, proposed)
    if len(validated.requirements) > 200 or len(validated.model_dump_json()) > 200000:
        raise ValueError("Use at most 200 requirements and 200,000 characters.")
    if duplicate_requirement_ids(validated):
        raise ValueError("Remove duplicate requirement descriptions before saving.")
    revision = requirements_revision(validated)
    with closing(sqlite3.connect(database, timeout=10)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            table = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='job_requirements'"
            ).fetchone()
            row = connection.execute(
                "SELECT payload FROM job_requirements WHERE capture_uuid=? AND jd_text_sha256=?",
                (str(capture_uuid), validated.jd_text_sha256),
            ).fetchone() if table else None
            if row is None:
                raise RequirementsReviewConflict("Extract this job's requirements first.")
            current = validate_requirements(capture, JobRequirements.model_validate_json(row[0]))
            current_revision = requirements_revision(current)
            if current_revision == revision:
                return {"requirements": validated.model_dump(mode="json"),
                        "revision": revision, "duplicate_groups": []}
            if current_revision != expected_revision:
                raise RequirementsReviewConflict(
                    "Requirements changed in another tab. Reopen the editor and review again."
                )
            connection.execute("""
                CREATE TABLE IF NOT EXISTS requirement_review_history (
                    review_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    capture_uuid TEXT NOT NULL,
                    previous_revision TEXT NOT NULL,
                    revision TEXT NOT NULL,
                    previous_payload TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)
            connection.execute("""
                INSERT INTO requirement_review_history
                (capture_uuid, previous_revision, revision, previous_payload, payload)
                VALUES (?, ?, ?, ?, ?)
            """, (str(capture_uuid), current_revision, revision,
                  current.model_dump_json(), validated.model_dump_json()))
            connection.execute(
                "UPDATE job_requirements SET payload=? WHERE capture_uuid=? AND jd_text_sha256=?",
                (validated.model_dump_json(), str(capture_uuid), validated.jd_text_sha256),
            )
    return {"requirements": validated.model_dump(mode="json"),
            "revision": revision, "duplicate_groups": []}
