"""Education persistence and evidence-reference validation."""

from uuid import uuid4

import pytest

from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.models import (
    CareerProfile,
    EducationRecord
)
from job_application_assistant.profile_markdown import (
    profile_from_markdown,
    profile_to_markdown
)
from job_application_assistant.profile_match import (
    ProfileEvidence,
    ProfileMatch,
    QualificationAssessment
)
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision,
    validate_profile_match
)


@pytest.fixture
def education_match():
    education = EducationRecord(
        qualification="Bachelor of Science",
        institution="Example University",
        field_of_study="Computer Science",
        status="completed",
        completion_date="2010"
    )
    profile = CareerProfile(education=[education])
    requirement = JobRequirement(
        description="Bachelor's degree.",
        kind="qualification",
        importance="required",
        source_excerpt="Bachelor's degree."
    )
    requirements = JobRequirements(
        capture_uuid=uuid4(),
        jd_text_sha256="a" * 64,
        requirements=[requirement]
    )
    evidence = [
        ProfileEvidence(
            record_type="education",
            record_uuid=education.education_uuid,
            field_name=field,
            excerpt=value
        )
        for field, value in [
            ("qualification", "Bachelor of Science"),
            ("status", "completed")
        ]
    ]
    match = ProfileMatch(
        capture_uuid=requirements.capture_uuid,
        requirements_sha256=requirements_revision(requirements),
        profile_sha256=profile_revision(profile),
        assessments=[
            QualificationAssessment(
                requirement_uuid=requirement.requirement_uuid,
                classification="strong_match",
                explanation="The profile records a completed bachelor's degree.",
                evidence=evidence
            )
        ],
    )
    return profile, requirements, match


def test_education_citations_reference_existing_fields(education_match):
    profile, requirements, match = education_match

    assert validate_profile_match(
        profile, requirements, match
    ) == match


@pytest.mark.parametrize(
    "problem",
    ["unknown_record", "unsupported_field", "absent_excerpt"]
)
def test_invalid_education_citation_rejected(education_match, problem):
    profile, requirements, match = education_match
    invalid = match.model_copy(deep=True)
    citation = invalid.assessments[0].evidence[0]

    if problem == "unknown_record":
        citation.record_uuid = uuid4()
    elif problem == "unsupported_field":
        citation.field_name = "education_uuid"
    else:
        citation.excerpt = "Doctor of Philosophy"

    with pytest.raises(ValueError):
        validate_profile_match(profile, requirements, invalid)


@pytest.mark.parametrize(
    "status",
    ["completed", "in_progress", "not_completed", "unknown"]
)
def test_markdown_preserves_education_status(status):
    profile = CareerProfile(
        education=[
            EducationRecord(
                qualification="Master of Science",
                status=status
            )
        ]
    )

    restored = profile_from_markdown(profile_to_markdown(profile))

    assert restored == profile
    assert restored.education[0].status == status
    assert restored.education[0].completion_date is None


def test_older_profile_loads_without_education_field():
    profile = profile_from_markdown(
        '# Career Profile\n\n```json\n'
        '{"roles": [], "stories": []}\n'
        '```\n'
    )

    assert profile.education == []


def test_duplicate_education_identifiers_rejected():
    record = EducationRecord(qualification="Bachelor of Science")

    with pytest.raises(ValueError, match="duplicate education_uuid"):
        CareerProfile(
            education=[record, record.model_copy(deep=True)]
        )