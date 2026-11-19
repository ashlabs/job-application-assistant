"""Store validated matches for exact profile and requirement versions."""

import sqlite3
from contextlib import closing
from pathlib import Path

from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_match import ProfileMatch
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision,
    validate_profile_match
)


def _validated_match(
    profile: CareerProfile,
    requirements: JobRequirements,
    match: ProfileMatch
) -> ProfileMatch:
    """Copy and validate a match against its source records."""
    copied = ProfileMatch.model_validate(
        match.model_dump(mode="json")
    )
    validate_profile_match(profile, requirements, copied)
    return copied


def save_profile_match(
    database: Path,
    profile: CareerProfile,
    requirements: JobRequirements,
    match: ProfileMatch
) -> ProfileMatch:
    """Save the first valid match for these exact source versions."""
    validated = _validated_match(profile, requirements, match)
    key = (
        str(validated.capture_uuid),
        validated.requirements_sha256,
        validated.profile_sha256
    )

    database.parent.mkdir(parents=True, exist_ok=True)

    with closing(
        sqlite3.connect(str(database), timeout=10)
    ) as connection:
        with connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS profile_matches (
                    capture_uuid TEXT NOT NULL,
                    requirements_sha256 TEXT NOT NULL,
                    profile_sha256 TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY (
                        capture_uuid,
                        requirements_sha256,
                        profile_sha256
                    )
                )
                """
            )

            connection.execute("BEGIN IMMEDIATE")

            row = connection.execute(
                """
                SELECT payload
                FROM profile_matches
                WHERE capture_uuid = ?
                  AND requirements_sha256 = ?
                  AND profile_sha256 = ?
                """,
                key,
            ).fetchone()

            if row is not None:
                existing = ProfileMatch.model_validate_json(row[0])
                return _validated_match(
                    profile, requirements, existing
                )

            connection.execute(
                """
                INSERT INTO profile_matches (
                    capture_uuid,
                    requirements_sha256,
                    profile_sha256,
                    payload
                )
                VALUES (?, ?, ?, ?)
                """,
                (*key, validated.model_dump_json())
            )

    return validated


def load_profile_match(
    database: Path,
    profile: CareerProfile,
    requirements: JobRequirements
) -> ProfileMatch | None:
    """Load a match only when both source versions still agree."""
    source_profile = CareerProfile.model_validate(
        profile.model_dump(mode="json")
    )
    source_requirements = JobRequirements.model_validate(
        requirements.model_dump(mode="json")
    )

    key = (
        str(source_requirements.capture_uuid),
        requirements_revision(source_requirements),
        profile_revision(source_profile)
    )

    if not database.exists():
        return None

    # Read-only mode prevents a read from creating a database.
    uri = database.resolve().as_uri() + "?mode=ro"

    with closing(
        sqlite3.connect(uri, uri=True, timeout=10)
    ) as connection:
        table = connection.execute(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'profile_matches'
            """
        ).fetchone()

        if table is None:
            return None

        row = connection.execute(
            """
            SELECT payload
            FROM profile_matches
            WHERE capture_uuid = ?
              AND requirements_sha256 = ?
              AND profile_sha256 = ?
            """,
            key
        ).fetchone()

    if row is None:
        return None

    match = ProfileMatch.model_validate_json(row[0])
    return _validated_match(
        source_profile, source_requirements, match
    )