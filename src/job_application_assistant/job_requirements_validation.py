"""Check extracted requirements against their captured source text."""

from hashlib import sha256

from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_requirements import JobRequirements


def jd_text_revision(text: str) -> str:
    """Hash the exact JD text without changing whitespace or case."""
    return sha256(text.encode("utf-8")).hexdigest()


def validate_requirements(
    capture: JobCapture,
    extraction: JobRequirements
) -> JobRequirements:
    """Return revalidated records only if source checks pass."""
    validated_capture = JobCapture.model_validate(
        capture.model_dump(mode="json")
    )
    validated = JobRequirements.model_validate(
        extraction.model_dump(mode="json")
    )

    if validated.capture_uuid != validated_capture.capture_uuid:
        raise ValueError(
            "Requirements reference a different capture."
        )

    expected_revision = jd_text_revision(validated_capture.jd_text)
    if validated.jd_text_sha256 != expected_revision:
        raise ValueError(
            "The JD text changed. Extract requirements again."
        )

    identifiers = [
        requirement.requirement_uuid
        for requirement in validated.requirements
    ]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(
            "Requirements contain duplicate requirement UUIDs."
        )

    for requirement in validated.requirements:
        if requirement.source_excerpt not in validated_capture.jd_text:
            raise ValueError(
                f"Requirement {requirement.requirement_uuid} "
                "has an excerpt absent from the captured JD. "
                f"Returned excerpt: {requirement.source_excerpt!r}"
            )

    return validated