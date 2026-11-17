"""Validated records for career experience capture."""

from typing import Annotated
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1)
]

class ExperienceStory(BaseModel):
    """A career story where missing details remain explicitly unknown."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True
    )

    story_uuid: UUID = Field(default_factory=uuid4)
    title: NonEmptyText

    situation: NonEmptyText | None = None
    task: NonEmptyText | None = None
    action: NonEmptyText | None = None
    result: NonEmptyText | None = None
    reflection: NonEmptyText | None = None
