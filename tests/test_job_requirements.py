"""Source-validation tests for extracted job requirements."""

from uuid import uuid4

import pytest

from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.job_requirements_validation import (
    jd_text_revision,
    validate_requirements
)


def make_capture():
    return JobCapture(
        source_url="https://example.com/jobs/product-manager",
        captured_at="2026-11-18T10:00:00-08:00",
        capture_method="paste",
        jd_text=(
            "Required: Experience conducting customer interviews.\n"
            "Preferred: Experience with SQL.\n"
            "Must work from the Seattle office three days per week."
        )
    )


def make_extraction(capture):
    return JobRequirements(
        capture_uuid=capture.capture_uuid,
        jd_text_sha256=jd_text_revision(capture.jd_text),
        requirements=[
            JobRequirement(
                description="Experience conducting customer interviews.",
                kind="qualification",
                importance="required",
                source_excerpt=(
                    "Required: Experience conducting customer interviews."
                )
            ),
            JobRequirement(
                description="Experience with SQL.",
                kind="qualification",
                importance="preferred",
                source_excerpt="Preferred: Experience with SQL."
            ),
            JobRequirement(
                description="Work from the Seattle office three days weekly.",
                kind="constraint",
                importance="required",
                source_excerpt=(
                    "Must work from the Seattle office three days per week."
                )
            )
        ]
    )


def test_valid_extraction_preserves_requirements_and_identifiers():
    capture = make_capture()
    extraction = make_extraction(capture)

    validated = validate_requirements(capture, extraction)
    restored = JobRequirements.model_validate_json(
        validated.model_dump_json()
    )

    assert validated == extraction
    assert restored == extraction
    assert restored.company_name is None
    assert restored.job_title is None
    assert [item.importance for item in restored.requirements] == [
        "required",
        "preferred",
        "required"
    ]
    assert restored.requirements[2].kind == "constraint"


def test_different_capture_rejected():
    capture = make_capture()
    extraction = make_extraction(capture)
    extraction.capture_uuid = uuid4()

    with pytest.raises(ValueError, match="different capture"):
        validate_requirements(capture, extraction)


def test_changed_source_text_rejected():
    capture = make_capture()
    extraction = make_extraction(capture)
    capture.jd_text += "\nAdditional qualification."

    with pytest.raises(ValueError, match="JD text changed"):
        validate_requirements(capture, extraction)


def test_excerpt_absent_from_source_rejected():
    capture = make_capture()
    extraction = make_extraction(capture)
    extraction.requirements[0].source_excerpt = (
        "Required: Ten years of executive leadership."
    )

    with pytest.raises(ValueError, match="excerpt absent"):
        validate_requirements(capture, extraction)


def test_duplicate_requirement_identifiers_rejected():
    capture = make_capture()
    extraction = make_extraction(capture)
    extraction.requirements[1].requirement_uuid = (
        extraction.requirements[0].requirement_uuid
    )

    with pytest.raises(ValueError, match="duplicate requirement UUIDs"):
        validate_requirements(capture, extraction)


def test_no_requirements_is_valid():
    capture = make_capture()
    extraction = JobRequirements(
        capture_uuid=capture.capture_uuid,
        jd_text_sha256=jd_text_revision(capture.jd_text),
    )

    validated = validate_requirements(capture, extraction)

    assert validated.requirements == []