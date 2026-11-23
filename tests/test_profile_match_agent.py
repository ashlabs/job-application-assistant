"""Tests for model-driven assessment response handling."""

import json
from uuid import uuid4

import pytest

from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.models import CareerProfile, ExperienceStory
from job_application_assistant.profile_match_agent import (
    MAX_MATCH_CHARACTERS,
    AssessmentResponse,
    EvidenceResponse,
    MatchResponse,
    create_profile_match_assessor
)
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision
)


class FakeModel:
    """Record inputs and return a predetermined response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def with_structured_output(self, schema, **kwargs):
        assert schema is MatchResponse
        assert kwargs == {
            "method": "json_schema",
            "strict": True,
        }
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.fixture
def assessment_example():
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
    response = MatchResponse(
        assessments=[
            AssessmentResponse(
                requirement_uuid=str(qualification.requirement_uuid),
                classification="strong_match",
                explanation="The profile documents customer interviews.",
                evidence=[
                    EvidenceResponse(
                        record_type="story",
                        record_uuid=str(story.story_uuid),
                        field_name="action",
                        excerpt="Interviewed customers"
                    )
                ]
            )
        ]
    )
    return profile, requirements, response


def test_assessor_returns_validated_match_without_changing_inputs(
    assessment_example
):
    profile, requirements, response = assessment_example
    original_profile = profile.model_dump(mode="json")
    original_requirements = requirements.model_dump(mode="json")
    model = FakeModel(response)

    result = create_profile_match_assessor(model)(profile, requirements)

    assert result.capture_uuid == requirements.capture_uuid
    assert result.profile_sha256 == profile_revision(profile)
    assert result.requirements_sha256 == requirements_revision(requirements)
    assert len(result.assessments) == 1
    assert result.assessments[0].classification == "strong_match"
    assert profile.model_dump(mode="json") == original_profile
    assert requirements.model_dump(mode="json") == original_requirements

    context = json.loads(model.calls[0][-1].content)
    assert context["career_profile"] == original_profile
    assert len(context["qualifications"]) == 1
    assert context["qualifications"][0]["kind"] == "qualification"


def test_no_requirements_skips_model_call(assessment_example):
    profile, requirements, _ = assessment_example
    requirements.requirements = []
    model = FakeModel(AssertionError("Unexpected model call"))

    result = create_profile_match_assessor(model)(profile, requirements)

    assert result.assessments == []
    assert model.calls == []


@pytest.mark.parametrize("problem", ["record", "excerpt", "missing"])
def test_invalid_model_assessment_rejected(assessment_example, problem):
    profile, requirements, response = assessment_example

    if problem == "record":
        response.assessments[0].evidence[0].record_uuid = str(uuid4())
    elif problem == "excerpt":
        response.assessments[0].evidence[0].excerpt = "Invented experience."
    else:
        response.assessments = []

    model = FakeModel(response)

    with pytest.raises(ValueError):
        create_profile_match_assessor(model)(profile, requirements)


def test_unstructured_response_rejected(assessment_example):
    profile, requirements, _ = assessment_example
    model = FakeModel({"assessments": []})

    with pytest.raises(ValueError, match="No structured assessment"):
        create_profile_match_assessor(model)(profile, requirements)


def test_oversized_input_rejected_before_model_call(assessment_example):
    profile, requirements, response = assessment_example
    profile.stories[0].action = "x" * (MAX_MATCH_CHARACTERS + 1)
    model = FakeModel(response)

    with pytest.raises(ValueError, match="exceeds"):
        create_profile_match_assessor(model)(profile, requirements)

    assert model.calls == []


def test_model_failure_propagates(assessment_example):
    profile, requirements, _ = assessment_example
    original = profile.model_dump(mode="json")
    model = FakeModel(RuntimeError("Simulated provider failure"))

    with pytest.raises(RuntimeError, match="Simulated provider failure"):
        create_profile_match_assessor(model)(profile, requirements)

    assert profile.model_dump(mode="json") == original