"""Calculate documented alignment using fixed qualification weights."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict

from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_match import ProfileMatch
from job_application_assistant.profile_match_validation import (
    validate_profile_match
)


IMPORTANCE_WEIGHTS = {
    "required": 2,
    "preferred": 1
}

# Integer half-credits avoid floating-point arithmetic during accumulation.
CLASSIFICATION_HALF_CREDITS = {
    "strong_match": 2,
    "transferable_experience": 1,
    "evidence_missing": 0,
    "confirmed_gap": 0
}


class DocumentedMatchScore(BaseModel):
    """A calculated score with its denominator and excluded requirements."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    percentage: float | None
    earned_weighted_credit: float
    possible_weighted_credit: int
    scored_qualification_count: int
    unspecified_qualification_uuids: list[UUID]
    constraint_uuids: list[UUID]


def score_profile_match(
    profile: CareerProfile,
    requirements: JobRequirements,
    match: ProfileMatch
) -> DocumentedMatchScore:
    """Validate an assessment, then calculate its documented-match score."""
    validated = validate_profile_match(profile, requirements, match)

    assessments = {
        item.requirement_uuid: item
        for item in validated.assessments
    }

    earned_half_credits = 0
    possible_credit = 0
    scored_count = 0
    unspecified = []
    constraints = []

    for requirement in requirements.requirements:
        if requirement.kind == "constraint":
            constraints.append(requirement.requirement_uuid)
            continue

        if requirement.importance == "unspecified":
            unspecified.append(requirement.requirement_uuid)
            continue

        weight = IMPORTANCE_WEIGHTS[requirement.importance]
        assessment = assessments[requirement.requirement_uuid]

        earned_half_credits += (
            weight
            * CLASSIFICATION_HALF_CREDITS[assessment.classification]
        )
        possible_credit += weight
        scored_count += 1

    percentage = (
        round(
            100 * earned_half_credits / (2 * possible_credit),
            1
        )
        if possible_credit
        else None
    )

    return DocumentedMatchScore(
        percentage=percentage,
        earned_weighted_credit=earned_half_credits / 2,
        possible_weighted_credit=possible_credit,
        scored_qualification_count=scored_count,
        unspecified_qualification_uuids=unspecified,
        constraint_uuids=constraints
    )