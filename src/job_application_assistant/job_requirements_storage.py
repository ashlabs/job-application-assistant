"""Persist validated AI extractions separately from approved profiles."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

from job_application_assistant.job_capture_storage import load_capture
from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.job_requirements_validation import (
    jd_text_revision,
    validate_requirements
)


def save_requirements(
    database_path: Path,
    extraction: JobRequirements
) -> JobRequirements:
    """Save the first valid extraction for this capture and source hash."""
    capture = load_capture(database_path, extraction.capture_uuid)
    validated = validate_requirements(capture, extraction)

    with closing(sqlite3.connect(database_path, timeout=10)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_requirements (
                    capture_uuid TEXT NOT NULL,
                    jd_text_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (capture_uuid, jd_text_sha256)
                )
                """
            )
            connection.execute("BEGIN IMMEDIATE")

            row = connection.execute(
                """
                SELECT payload
                FROM job_requirements
                WHERE capture_uuid = ? AND jd_text_sha256 = ?
                """,
                (
                    str(validated.capture_uuid),
                    validated.jd_text_sha256
                )
            ).fetchone()

            if row is not None:
                existing = JobRequirements.model_validate_json(row[0])
                return validate_requirements(capture, existing)

            connection.execute(
                """
                INSERT INTO job_requirements (
                    capture_uuid,
                    jd_text_sha256,
                    payload
                )
                VALUES (?, ?, ?)
                """,
                (
                    str(validated.capture_uuid),
                    validated.jd_text_sha256,
                    validated.model_dump_json()
                )
            )

    return validated


def load_requirements(
    database_path: Path,
    capture_uuid: UUID
) -> JobRequirements | None:
    """Return this capture's stored extraction, or None if not extracted."""
    capture = load_capture(database_path, capture_uuid)
    revision = jd_text_revision(capture.jd_text)

    with closing(sqlite3.connect(database_path, timeout=10)) as connection:
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'job_requirements'
            """
        ).fetchone()

        if table is None:
            return None

        row = connection.execute(
            """
            SELECT payload
            FROM job_requirements
            WHERE capture_uuid = ? AND jd_text_sha256 = ?
            """,
            (str(capture_uuid), revision)
        ).fetchone()

    if row is None:
        return None

    extraction = JobRequirements.model_validate_json(row[0])
    return validate_requirements(capture, extraction)
