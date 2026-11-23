"""Store matches for exact profile, requirements, and scoring-rule versions."""

import json
import sqlite3
from contextlib import closing
from pathlib import Path

from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_match import ProfileMatch
from job_application_assistant.profile_match_validation import (
    profile_revision, requirements_revision, validate_profile_match,
)
from job_application_assistant.scoring_rules import SCORING_RULES_VERSION


_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS profile_matches (
        capture_uuid TEXT NOT NULL,
        requirements_sha256 TEXT NOT NULL,
        profile_sha256 TEXT NOT NULL,
        scoring_rules_version TEXT NOT NULL,
        payload TEXT NOT NULL,
        PRIMARY KEY (
            capture_uuid, requirements_sha256, profile_sha256,
            scoring_rules_version
        )
    )
"""


def _versioned_table(connection):
    """Upgrade on an explicit write, retaining every legacy payload."""
    columns = {row[1] for row in connection.execute("PRAGMA table_info(profile_matches)")}
    if columns and "scoring_rules_version" not in columns:
        connection.execute("ALTER TABLE profile_matches RENAME TO profile_matches_legacy_migration")
        connection.execute(_CREATE_TABLE)
        connection.execute("""
            INSERT INTO profile_matches
            (capture_uuid, requirements_sha256, profile_sha256, scoring_rules_version, payload)
            SELECT capture_uuid, requirements_sha256, profile_sha256, 'unversioned', payload
            FROM profile_matches_legacy_migration
        """)
        connection.execute("DROP TABLE profile_matches_legacy_migration")
    else:
        connection.execute(_CREATE_TABLE)


def _validated_match(profile, requirements, match):
    """Copy and validate sources, evidence, and current scoring policy."""
    copied = ProfileMatch.model_validate(match.model_dump(mode="json"))
    return validate_profile_match(profile, requirements, copied)


def _read_payload(payload, profile, requirements):
    """Never silently label an unversioned payload with the current policy."""
    data = json.loads(payload)
    if data.get("scoring_rules_version") != SCORING_RULES_VERSION:
        raise ValueError("Stored match has an inconsistent scoring-rule version.")
    return _validated_match(profile, requirements, ProfileMatch.model_validate(data))


def save_profile_match(
    database: Path,
    profile: CareerProfile,
    requirements: JobRequirements,
    match: ProfileMatch,
) -> ProfileMatch:
    """Keep the first valid assessment per source and rule-version key."""
    validated = _validated_match(profile, requirements, match)
    key = (str(validated.capture_uuid), validated.requirements_sha256,
           validated.profile_sha256, validated.scoring_rules_version)
    database.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(str(database), timeout=10)) as connection:
        with connection:
            connection.execute("BEGIN IMMEDIATE")
            _versioned_table(connection)
            row = connection.execute("""
                SELECT payload FROM profile_matches
                WHERE capture_uuid=? AND requirements_sha256=?
                  AND profile_sha256=? AND scoring_rules_version=?
            """, key).fetchone()
            if row is not None:
                return _read_payload(row[0], profile, requirements)
            connection.execute("""
                INSERT INTO profile_matches
                (capture_uuid, requirements_sha256, profile_sha256, scoring_rules_version, payload)
                VALUES (?, ?, ?, ?, ?)
            """, (*key, validated.model_dump_json()))
    return validated


def load_profile_match(
    database: Path,
    profile: CareerProfile,
    requirements: JobRequirements,
) -> ProfileMatch | None:
    """Read only current versions; reading never migrates or calls AI."""
    source_profile = CareerProfile.model_validate(profile.model_dump(mode="json"))
    source_requirements = JobRequirements.model_validate(requirements.model_dump(mode="json"))
    key = (str(source_requirements.capture_uuid), requirements_revision(source_requirements),
           profile_revision(source_profile), SCORING_RULES_VERSION)
    if not database.exists():
        return None
    uri = database.resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=10)) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(profile_matches)")}
        if "scoring_rules_version" not in columns:
            return None
        row = connection.execute("""
            SELECT payload FROM profile_matches
            WHERE capture_uuid=? AND requirements_sha256=?
              AND profile_sha256=? AND scoring_rules_version=?
        """, key).fetchone()
    if row is None:
        return None
    return _read_payload(row[0], source_profile, source_requirements)
