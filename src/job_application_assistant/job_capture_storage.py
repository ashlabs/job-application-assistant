"""Local storage for confirmed job-description captures."""

import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

from job_application_assistant.job_capture import JobCapture


class CaptureConflictError(ValueError):
    """A capture UUID was reused with different content."""


def save_capture(database_path: Path, capture: JobCapture) -> bool:
    """Save a capture; return True if new, False for an identical retry."""
    validated = JobCapture.model_validate(
        capture.model_dump(mode="json")
    )
    capture_uuid = str(validated.capture_uuid)
    payload = validated.model_dump_json()

    database_path.parent.mkdir(parents=True, exist_ok=True)

    with closing(sqlite3.connect(database_path, timeout=10)) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS job_captures (
                    capture_uuid TEXT PRIMARY KEY,
                    payload TEXT NOT NULL
                )
                """
            )

            # Keep the lookup and insert in one write transaction.
            connection.execute("BEGIN IMMEDIATE")

            row = connection.execute(
                """
                SELECT payload
                FROM job_captures
                WHERE capture_uuid = ?
                """,
                (capture_uuid,)
            ).fetchone()

            if row is not None:
                existing = JobCapture.model_validate_json(row[0])

                if existing != validated:
                    raise CaptureConflictError(
                        "This capture UUID already exists with different "
                        "content. Create a new capture UUID."
                    )

                return False

            connection.execute(
                """
                INSERT INTO job_captures (capture_uuid, payload)
                VALUES (?, ?)
                """,
                (capture_uuid, payload)
            )

    return True


def load_capture(
    database_path: Path,
    capture_uuid: UUID
) -> JobCapture:
    """Load a saved capture, raising KeyError if it does not exist."""
    if not database_path.exists():
        raise KeyError(f"Capture not found: {capture_uuid}")

    with closing(sqlite3.connect(database_path, timeout=10)) as connection:
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'job_captures'
            """
        ).fetchone()

        if table is None:
            raise KeyError(f"Capture not found: {capture_uuid}")

        row = connection.execute(
            """
            SELECT payload
            FROM job_captures
            WHERE capture_uuid = ?
            """,
            (str(capture_uuid),)
        ).fetchone()

    if row is None:
        raise KeyError(f"Capture not found: {capture_uuid}")

    capture = JobCapture.model_validate_json(row[0])

    if capture.capture_uuid != capture_uuid:
        raise CaptureConflictError(
            "Stored capture identifier does not match the requested capture."
        )

    return capture

def list_captures(database_path: Path) -> list[JobCapture]:
    """Return saved captures ordered by capture time, newest first."""
    if not database_path.exists():
        return []

    with closing(sqlite3.connect(database_path, timeout=10)) as connection:
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'job_captures'
            """
        ).fetchone()

        if table is None:
            return []

        rows = connection.execute(
            """
            SELECT capture_uuid, payload
            FROM job_captures
            """
        ).fetchall()

    captures = []

    for stored_uuid, payload in rows:
        capture = JobCapture.model_validate_json(payload)

        if str(capture.capture_uuid) != stored_uuid:
            raise CaptureConflictError(
                "Stored capture identifier does not match its content."
            )

        captures.append(capture)

    return sorted(
        captures,
        key=lambda capture: (
            capture.captured_at,
            str(capture.capture_uuid)
        ),
        reverse=True
    )