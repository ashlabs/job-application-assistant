"""Tests for requirement extraction without API calls."""

import json

import pytest

from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_requirements_agent import (
    MAX_JD_CHARACTERS,
    ExtractionResponse,
    RequirementResponse,
    create_requirements_extractor
)
from job_application_assistant.job_requirements_validation import (
    jd_text_revision
)


class FakeModel:
    """Record model inputs and return a fixed response."""

    def __init__(self, response):
        self.response = response
        self.calls = []

    def with_structured_output(self, schema, **kwargs):
        assert schema is ExtractionResponse
        assert kwargs == {
            "method": "json_schema",
            "strict": True
        }
        return self

    def invoke(self, messages):
        self.calls.append(messages)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_capture():
    return JobCapture(
        source_url="https://example.com/jobs/product-manager",
        page_title="Page title is not extraction evidence",
        captured_at="2026-11-18T10:00:00-08:00",
        capture_method="paste",
        jd_text=(
            "Required: Experience conducting customer interviews.\n"
            "Preferred: Experience with SQL.\n"
            "Must work from the Seattle office three days per week."
        )
    )


def make_response():
    return ExtractionResponse(
        company_name=None,
        job_title=None,
        requirements=[
            RequirementResponse(
                description="Experience conducting customer interviews.",
                kind="qualification",
                importance="required",
                source_excerpt=(
                    "Required: Experience conducting customer interviews."
                )
            ),
            RequirementResponse(
                description="Experience with SQL.",
                kind="qualification",
                importance="preferred",
                source_excerpt="Preferred: Experience with SQL.",
            ),
            RequirementResponse(
                description="Attend the Seattle office three days weekly.",
                kind="constraint",
                importance="required",
                source_excerpt=(
                    "Must work from the Seattle office three days per week."
                )
            )
        ]
    )


def test_extractor_builds_source_linked_records_without_mutating_capture():
    capture = make_capture()
    original = capture.model_dump(mode="json")
    model = FakeModel(make_response())

    result = create_requirements_extractor(model)(capture)

    assert result.capture_uuid == capture.capture_uuid
    assert result.jd_text_sha256 == jd_text_revision(capture.jd_text)
    assert result.company_name is None
    assert result.job_title is None
    assert len(result.requirements) == 3
    assert len({
        item.requirement_uuid
        for item in result.requirements
    }) == 3
    assert result.requirements[1].importance == "preferred"
    assert result.requirements[2].kind == "constraint"
    assert capture.model_dump(mode="json") == original

    assert len(model.calls) == 1
    source_message = model.calls[0][-1]
    assert json.loads(source_message.content) == {
        "jd_text": capture.jd_text
    }


def test_extractor_rejects_excerpt_missing_from_source():
    response = make_response()
    response.requirements[0].source_excerpt = (
        "Ten years of executive leadership required."
    )
    model = FakeModel(response)

    with pytest.raises(ValueError, match="excerpt absent"):
        create_requirements_extractor(model)(make_capture())


def test_oversized_capture_rejected_before_model_call():
    capture = make_capture()
    capture.jd_text = "x" * (MAX_JD_CHARACTERS + 1)
    model = FakeModel(make_response())

    with pytest.raises(ValueError, match="extraction limit"):
        create_requirements_extractor(model)(capture)

    assert model.calls == []


def test_model_failure_propagates_without_mutating_capture():
    capture = make_capture()
    original = capture.model_dump(mode="json")
    model = FakeModel(RuntimeError("Simulated model failure"))

    with pytest.raises(RuntimeError, match="Simulated model failure"):
        create_requirements_extractor(model)(capture)

    assert capture.model_dump(mode="json") == original


def test_unstructured_response_rejected():
    model = FakeModel({"requirements": []})

    with pytest.raises(ValueError, match="No structured"):
        create_requirements_extractor(model)(make_capture())