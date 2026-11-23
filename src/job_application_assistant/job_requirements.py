"""Structured requirements extracted from a captured job description."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from job_application_assistant.models import NonEmptyText


class JobRequirement(BaseModel):
    """One qualification or practical constraint supported by JD text."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True
    )

    requirement_uuid: UUID = Field(default_factory=uuid4)
    description: NonEmptyText
    kind: Literal["qualification", "constraint"]
    importance: Literal["required", "preferred", "unspecified"]
    source_excerpt: NonEmptyText


class JobRequirements(BaseModel):
    """An extraction linked to the exact captured JD text."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True
    )

    capture_uuid: UUID
    jd_text_sha256: NonEmptyText
    company_name: NonEmptyText | None = None
    job_title: NonEmptyText | None = None
    requirements: list[JobRequirement] = Field(default_factory=list)