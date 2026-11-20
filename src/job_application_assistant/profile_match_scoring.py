"""Calculate documented alignment using fixed qualification weights."""

from uuid import UUID
from typing import Literal

from pydantic import BaseModel, ConfigDict

from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_match import ProfileMatch
from job_application_assistant.profile_match_validation import (
    validate_profile_match
)


from job_application_assistant.scoring_rules import (
    SCORING_RULES_VERSION, IMPORTANCE_WEIGHTS, CLASSIFICATION_HALF_CREDITS,
)


class QualificationCredit(BaseModel):
    """Python-calculated contribution for one qualification, in JD order."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    requirement_uuid: UUID
    importance: Literal["required", "preferred", "unspecified"]
    classification: Literal[
        "strong_match", "transferable_experience", "evidence_missing", "confirmed_gap"
    ]
    weight: int | None
    classification_credit: float
    earned_weighted_credit: float
    possible_weighted_credit: int
    exclusion_reason: Literal["unspecified_importance"] | None


class DocumentedMatchScore(BaseModel):
    """A calculated score with its denominator and excluded requirements."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    scoring_rules_version: str
    contributions: list[QualificationCredit]
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
    contributions = []

    for requirement in requirements.requirements:
        if requirement.kind == "constraint":
            constraints.append(requirement.requirement_uuid)
            continue

        assessment = assessments[requirement.requirement_uuid]
        half_credit = CLASSIFICATION_HALF_CREDITS[assessment.classification]
        weight = IMPORTANCE_WEIGHTS.get(requirement.importance)
        contributions.append(QualificationCredit(
            requirement_uuid=requirement.requirement_uuid,
            importance=requirement.importance,
            classification=assessment.classification,
            weight=weight,
            classification_credit=half_credit / 2,
            earned_weighted_credit=(weight or 0) * half_credit / 2,
            possible_weighted_credit=weight or 0,
            exclusion_reason=("unspecified_importance" if weight is None else None),
        ))
        if weight is None:
            unspecified.append(requirement.requirement_uuid)
            continue

        earned_half_credits += weight * half_credit
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
        scoring_rules_version=SCORING_RULES_VERSION,
        contributions=contributions,
        percentage=percentage,
        earned_weighted_credit=earned_half_credits / 2,
        possible_weighted_credit=possible_credit,
        scored_qualification_count=scored_count,
        unspecified_qualification_uuids=unspecified,
        constraint_uuids=constraints
    )
