"""Tests for version-specific profile match storage."""

import sqlite3
from uuid import uuid4

import pytest

from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_match import (
    ProfileMatch,
    QualificationAssessment
)
from job_application_assistant.profile_match_storage import (
    load_profile_match,
    save_profile_match
)
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision
)


@pytest.fixture
def sources():
    profile = CareerProfile()
    requirement = JobRequirement(
        description="Experience conducting customer interviews.",
        kind="qualification",
        importance="required",
        source_excerpt="Experience conducting customer interviews."
    )
    requirements = JobRequirements(
        capture_uuid=uuid4(),
        jd_text_sha256="a" * 64,
        company_name="Example Company",
        job_title="Product Manager",
        requirements=[requirement]
    )
    match = ProfileMatch(
        capture_uuid=requirements.capture_uuid,
        requirements_sha256=requirements_revision(requirements),
        profile_sha256=profile_revision(profile),
        assessments=[
            QualificationAssessment(
                requirement_uuid=requirement.requirement_uuid,
                classification="evidence_missing",
                explanation="The profile contains no experience records.",
                evidence=[]
            )
        ]
    )
    return profile, requirements, match


def test_match_survives_database_reopening(tmp_path, sources):
    database = tmp_path / "matches.sqlite"
    profile, requirements, match = sources

    saved = save_profile_match(
        database, profile, requirements, match
    )
    loaded = load_profile_match(database, profile, requirements)

    assert saved == match
    assert loaded == match


def test_retry_preserves_first_saved_match(tmp_path, sources):
    database = tmp_path / "matches.sqlite"
    profile, requirements, match = sources
    save_profile_match(database, profile, requirements, match)

    alternative = match.model_copy(deep=True)
    alternative.assessments[0].explanation = (
        "No supporting experience is documented."
    )

    returned = save_profile_match(
        database, profile, requirements, alternative
    )

    assert returned == match
    assert load_profile_match(
        database, profile, requirements
    ) == match

    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM profile_matches"
        ).fetchone()[0]

    assert count == 1


@pytest.mark.parametrize("changed_source", ["profile", "requirements"])
def test_changed_source_does_not_reuse_match(
    tmp_path, sources, changed_source
):
    database = tmp_path / "matches.sqlite"
    profile, requirements, match = sources
    save_profile_match(database, profile, requirements, match)

    changed_profile = profile.model_copy(deep=True)
    changed_requirements = requirements.model_copy(deep=True)

    if changed_source == "profile":
        changed_profile = CareerProfile.model_validate(
            {
                "roles": [
                    {
                        "employer": "Example Company",
                        "job_title": "Product Manager",
                    }
                ],
                "stories": []
            }
        )
    else:
        changed_requirements.requirements[0].importance = "preferred"

    assert load_profile_match(
        database, changed_profile, changed_requirements
    ) is None

    # The original version remains available.
    assert load_profile_match(
        database, profile, requirements
    ) == match


def test_invalid_match_rejected_before_database_creation(
    tmp_path, sources
):
    database = tmp_path / "matches.sqlite"
    profile, requirements, match = sources
    invalid = match.model_copy(deep=True)
    invalid.profile_sha256 = "b" * 64

    with pytest.raises(ValueError):
        save_profile_match(
            database, profile, requirements, invalid
        )

    assert not database.exists()


def test_loading_missing_database_does_not_create_it(
    tmp_path, sources
):
    database = tmp_path / "missing.sqlite"
    profile, requirements, _ = sources

    assert load_profile_match(
        database, profile, requirements
    ) is None
    assert not database.exists()


def test_corrupted_saved_match_is_rejected(tmp_path, sources):
    database = tmp_path / "matches.sqlite"
    profile, requirements, match = sources
    save_profile_match(database, profile, requirements, match)

    corrupted = match.model_copy(deep=True)
    corrupted.profile_sha256 = "c" * 64

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE profile_matches SET payload = ?",
            (corrupted.model_dump_json(),),
        )

    with pytest.raises(ValueError):
        load_profile_match(database, profile, requirements)