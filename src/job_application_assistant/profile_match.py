"""Evidence-backed assessments of documented qualification alignment."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from job_application_assistant.models import NonEmptyText


class ProfileEvidence(BaseModel):
    """An excerpt from a specific field in the approved career profile."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True
    )

    record_type: Literal["role", "story", "education"]
    record_uuid: UUID
    field_name: NonEmptyText
    excerpt: NonEmptyText


class QualificationAssessment(BaseModel):
    """An assessment of one qualification, with supporting evidence."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True
    )

    requirement_uuid: UUID
    classification: Literal[
        "strong_match",
        "transferable_experience",
        "evidence_missing",
        "confirmed_gap"
    ]
    explanation: NonEmptyText
    evidence: list[ProfileEvidence] = Field(default_factory=list)

    @model_validator(mode="after")
    def require_supporting_evidence(self) -> "QualificationAssessment":
        """Require evidence for positive matches and confirmed gaps."""
        if (
            self.classification != "evidence_missing"
            and not self.evidence
        ):
            raise ValueError(
                "This classification requires supporting profile evidence."
            )

        return self


class ProfileMatch(BaseModel):
    """Assessments tied to specific requirements and profile versions."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True
    )

    capture_uuid: UUID
    requirements_sha256: NonEmptyText
    profile_sha256: NonEmptyText
    assessments: list[QualificationAssessment] = Field(default_factory=list)