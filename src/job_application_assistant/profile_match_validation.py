"""Validate assessment coverage, source versions, and profile evidence."""

import json
from hashlib import sha256

from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_match import ProfileMatch


ROLE_EVIDENCE_FIELDS = {
    "employer",
    "job_title",
    "start_date",
    "end_date",
    "responsibilities",
    "scope"
}

STORY_EVIDENCE_FIELDS = {
    "title",
    "situation",
    "task",
    "action",
    "result",
    "reflection"
}


def _data_revision(data: dict) -> str:
    """Hash a consistent JSON representation of validated data."""
    serialized = json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False
    )
    return sha256(serialized.encode("utf-8")).hexdigest()


def profile_revision(profile: CareerProfile) -> str:
    """Identify the exact profile data used for assessment."""
    validated = CareerProfile.model_validate(
        profile.model_dump(mode="json")
    )
    return _data_revision(validated.model_dump(mode="json"))


def requirements_revision(requirements: JobRequirements) -> str:
    """Identify the exact extracted requirements used for assessment."""
    validated = JobRequirements.model_validate(
        requirements.model_dump(mode="json")
    )
    return _data_revision(validated.model_dump(mode="json"))


def validate_profile_match(
    profile: CareerProfile,
    requirements: JobRequirements,
    match: ProfileMatch
) -> ProfileMatch:
    """Reject stale, incomplete, or incorrectly referenced assessments."""
    validated_profile = CareerProfile.model_validate(
        profile.model_dump(mode="json")
    )
    validated_requirements = JobRequirements.model_validate(
        requirements.model_dump(mode="json")
    )
    validated_match = ProfileMatch.model_validate(
        match.model_dump(mode="json")
    )

    if validated_match.capture_uuid != validated_requirements.capture_uuid:
        raise ValueError("The assessment references a different capture.")

    if validated_match.profile_sha256 != profile_revision(validated_profile):
        raise ValueError("The career profile changed. Assess it again.")

    if (
        validated_match.requirements_sha256
        != requirements_revision(validated_requirements)
    ):
        raise ValueError("The requirements changed. Assess them again.")

    requirement_ids = [
        item.requirement_uuid
        for item in validated_requirements.requirements
    ]
    if len(requirement_ids) != len(set(requirement_ids)):
        raise ValueError("Requirements contain duplicate identifiers.")

    qualification_ids = {
        item.requirement_uuid
        for item in validated_requirements.requirements
        if item.kind == "qualification"
    }
    assessed_ids = [
        item.requirement_uuid
        for item in validated_match.assessments
    ]

    if len(assessed_ids) != len(set(assessed_ids)):
        raise ValueError("A qualification was assessed more than once.")

    if set(assessed_ids) != qualification_ids:
        raise ValueError(
            "Assess every qualification exactly once. "
            "Do not include practical constraints."
        )

    roles = {
        role.role_uuid: role.model_dump(mode="json")
        for role in validated_profile.roles
    }
    stories = {
        story.story_uuid: story.model_dump(mode="json")
        for story in validated_profile.stories
    }

    for assessment in validated_match.assessments:
        for evidence in assessment.evidence:
            if evidence.record_type == "role":
                record = roles.get(evidence.record_uuid)
                allowed_fields = ROLE_EVIDENCE_FIELDS
            else:
                record = stories.get(evidence.record_uuid)
                allowed_fields = STORY_EVIDENCE_FIELDS

            if record is None:
                raise ValueError("Evidence references an unknown profile record.")

            if evidence.field_name not in allowed_fields:
                raise ValueError("Evidence references an unsupported field.")

            value = record[evidence.field_name]

            if isinstance(value, str):
                source_texts = [value]
            elif isinstance(value, list):
                source_texts = [
                    item for item in value if isinstance(item, str)
                ]
            else:
                source_texts = []

            if not any(
                evidence.excerpt in source
                for source in source_texts
            ):
                raise ValueError(
                    "The evidence excerpt is absent from its cited field."
                )

    return validated_match