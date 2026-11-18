"""Tests for evidence-backed qualification assessments."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.models import CareerProfile, ExperienceStory
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
def match_example():
    story = ExperienceStory(
        title="Customer discovery",
        action="Interviewed customers and prioritized onboarding changes."
    )
    profile = CareerProfile(stories=[story])

    qualification = JobRequirement(
        description="Experience conducting customer interviews.",
        kind="qualification",
        importance="required",
        source_excerpt="Experience conducting customer interviews."
    )
    constraint = JobRequirement(
        description="Work in Seattle.",
        kind="constraint",
        importance="required",
        source_excerpt="Work in Seattle."
    )
    requirements = JobRequirements(
        capture_uuid=uuid4(),
        jd_text_sha256="0" * 64,
        requirements=[qualification, constraint]
    )

    assessment = QualificationAssessment(
        requirement_uuid=qualification.requirement_uuid,
        classification="strong_match",
        explanation="The profile documents direct customer interviews.",
        evidence=[
            ProfileEvidence(
                record_type="story",
                record_uuid=story.story_uuid,
                field_name="action",
                excerpt="Interviewed customers"
            )
        ]
    )
    match = ProfileMatch(
        capture_uuid=requirements.capture_uuid,
        requirements_sha256=requirements_revision(requirements),
        profile_sha256=profile_revision(profile),
        assessments=[assessment]
    )

    return profile, requirements, match


def test_valid_match_round_trip_preserves_evidence(match_example):
    profile, requirements, match = match_example

    validated = validate_profile_match(profile, requirements, match)
    restored = ProfileMatch.model_validate_json(
        validated.model_dump_json()
    )

    assert restored == match
    assert restored.assessments[0].evidence[0].excerpt == (
        "Interviewed customers"
    )


@pytest.mark.parametrize(
    "classification",
    ["strong_match", "transferable_experience", "confirmed_gap"],
)
def test_supported_classifications_require_evidence(classification):
    with pytest.raises(ValidationError, match="supporting profile evidence"):
        QualificationAssessment(
            requirement_uuid=uuid4(),
            classification=classification,
            explanation="An assessment without supporting evidence."
        )


def test_missing_evidence_can_be_reported_without_citations(match_example):
    profile, requirements, match = match_example
    requirement_uuid = match.assessments[0].requirement_uuid

    match.assessments = [
        QualificationAssessment(
            requirement_uuid=requirement_uuid,
            classification="evidence_missing",
            explanation="No sufficient evidence is documented."
        )
    ]

    validated = validate_profile_match(profile, requirements, match)

    assert validated.assessments[0].classification == "evidence_missing"
    assert validated.assessments[0].evidence == []


@pytest.mark.parametrize(
    "problem",
    ["missing", "duplicate", "constraint", "unknown"]
)
def test_invalid_qualification_coverage_rejected(match_example, problem):
    profile, requirements, match = match_example

    if problem == "missing":
        match.assessments = []
    elif problem == "duplicate":
        match.assessments.append(
            match.assessments[0].model_copy(deep=True)
        )
    elif problem == "constraint":
        match.assessments[0].requirement_uuid = (
            requirements.requirements[1].requirement_uuid
        )
    else:
        match.assessments[0].requirement_uuid = uuid4()

    with pytest.raises(ValueError):
        validate_profile_match(profile, requirements, match)


@pytest.mark.parametrize("changed_source", ["profile", "requirements"])
def test_changed_sources_invalidate_match(match_example, changed_source):
    profile, requirements, match = match_example

    if changed_source == "profile":
        profile.stories[0].action = "Reviewed customer support tickets."
    else:
        requirements.requirements[0].importance = "preferred"

    with pytest.raises(ValueError, match="changed"):
        validate_profile_match(profile, requirements, match)


@pytest.mark.parametrize(
    ("problem", "expected_message"),
    [
        ("record", "unknown profile record"),
        ("field", "unsupported field"),
        ("excerpt", "absent from its cited field"),
    ]
)
def test_invalid_evidence_reference_rejected(
    match_example,
    problem,
    expected_message
):
    profile, requirements, match = match_example
    evidence = match.assessments[0].evidence[0]

    if problem == "record":
        evidence.record_uuid = uuid4()
    elif problem == "field":
        evidence.field_name = "story_uuid"
    else:
        evidence.excerpt = "Managed a team of 50 engineers."

    with pytest.raises(ValueError, match=expected_message):
        validate_profile_match(profile, requirements, match)