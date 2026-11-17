"""Validated records for career experience capture."""

from typing import Annotated
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator
)


NonEmptyText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1)
]

class EmploymentRecord(BaseModel):
    """Employment details collected from the user."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    role_uuid: UUID = Field(default_factory=uuid4)
    employer: NonEmptyText
    job_title: NonEmptyText

    start_date: NonEmptyText | None = None
    end_date: NonEmptyText | None = None
    is_current: bool | None = None

    responsibilities: list[NonEmptyText] = Field(default_factory=list)
    scope: NonEmptyText | None = None

class ExperienceStory(BaseModel):
    """A career story where missing details remain explicitly unknown."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True
    )

    story_uuid: UUID = Field(default_factory=uuid4)
    role_uuid: UUID | None = None
    title: NonEmptyText

    situation: NonEmptyText | None = None
    task: NonEmptyText | None = None
    action: NonEmptyText | None = None
    result: NonEmptyText | None = None
    reflection: NonEmptyText | None = None

class CareerProfile(BaseModel):
    """Career records with validated identifiers and role references."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True
    )

    roles: list[EmploymentRecord] = Field(default_factory=list)
    stories: list[ExperienceStory] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_record_links(self) -> "CareerProfile":
        """Reject duplicate identifiers and references to missing roles."""
        role_ids = [role.role_uuid for role in self.roles]
        story_ids = [story.story_uuid for story in self.stories]

        if len(role_ids) != len(set(role_ids)):
            raise ValueError(
                "Employment records have duplicate role_uuid values."
                )

        if len(story_ids) != len(set(story_ids)):
            raise ValueError(
                "Experience stories have duplicate story_uuid values."
                )

        known_roles = set(role_ids)

        for story in self.stories:
            if (
                story.role_uuid is not None
                and story.role_uuid not in known_roles
            ):
                raise ValueError(
                    f"Story {story.story_uuid} references an unknown role."
                )

        return self
