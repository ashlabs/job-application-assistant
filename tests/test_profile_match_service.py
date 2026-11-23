"""Tests for assessing the saved profile without model calls."""

from uuid import uuid4

import pytest

from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.models import CareerProfile, ExperienceStory
from job_application_assistant.profile_markdown import profile_to_markdown
from job_application_assistant.profile_match import (
    ProfileMatch,
    QualificationAssessment
)
from job_application_assistant.profile_match_service import (
    assess_saved_profile
)
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision
)


@pytest.fixture
def saved_example(tmp_path):
    profile = CareerProfile(
        stories=[
            ExperienceStory(
                title="Customer discovery",
                action="Interviewed customers."
            )
        ]
    )
    path = tmp_path / "career_profile.md"
    path.write_text(profile_to_markdown(profile), encoding="utf-8")

    requirements = JobRequirements(
        capture_uuid=uuid4(),
        jd_text_sha256="0" * 64,
        requirements=[
            JobRequirement(
                description="8 years of product management experience.",
                kind="qualification",
                importance="required",
                source_excerpt="8 years of product management experience."
            )
        ]
    )
    return path, profile, requirements


def missing_evidence_match(profile, requirements):
    """Return a valid assessment with no claimed experience."""
    return ProfileMatch(
        capture_uuid=requirements.capture_uuid,
        profile_sha256=profile_revision(profile),
        requirements_sha256=requirements_revision(requirements),
        assessments=[
            QualificationAssessment(
                requirement_uuid=item.requirement_uuid,
                classification="evidence_missing",
                explanation="The profile does not document duration."
            )
            for item in requirements.requirements
            if item.kind == "qualification"
        ]
    )


def test_service_reads_saved_profile_and_calculates_score(saved_example):
    path, profile, requirements = saved_example
    original_bytes = path.read_bytes()
    calls = []

    def assessor(received_profile, received_requirements):
        calls.append((received_profile, received_requirements))
        return missing_evidence_match(
            received_profile,
            received_requirements
        )

    report = assess_saved_profile(
        path,
        requirements,
        assessor=assessor
    )

    assert calls == [(profile, requirements)]
    assert report.score.percentage == 0.0
    assert report.score.possible_weighted_credit == 2
    assert report.match.profile_sha256 == profile_revision(profile)
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize("problem", ["missing", "invalid"])
def test_unavailable_profile_blocks_assessor(saved_example, problem):
    path, _, requirements = saved_example
    calls = []

    if problem == "missing":
        path.unlink()
        expected_error = FileNotFoundError
    else:
        path.write_text("Unsupported profile content.", encoding="utf-8")
        expected_error = ValueError

    def assessor(profile, source):
        calls.append(True)
        raise AssertionError("Assessor should not run.")

    with pytest.raises(expected_error):
        assess_saved_profile(path, requirements, assessor=assessor)

    assert calls == []


def test_profile_change_during_assessment_rejected(saved_example):
    path, _, requirements = saved_example

    def assessor(profile, source):
        match = missing_evidence_match(profile, source)

        updated = profile.model_copy(deep=True)
        updated.stories[0].action = "Reviewed customer support tickets."
        path.write_text(
            profile_to_markdown(updated),
            encoding="utf-8"
        )
        return match

    with pytest.raises(ValueError, match="changed during assessment"):
        assess_saved_profile(path, requirements, assessor=assessor)


def test_invalid_assessment_cannot_produce_report(saved_example):
    path, _, requirements = saved_example

    def assessor(profile, source):
        match = missing_evidence_match(profile, source)
        match.assessments[0].requirement_uuid = uuid4()
        return match

    with pytest.raises(ValueError, match="Assess every qualification"):
        assess_saved_profile(path, requirements, assessor=assessor)