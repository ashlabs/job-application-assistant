"""Validated job-description captures and source metadata."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl
)

from job_application_assistant.models import NonEmptyText


class JobCapture(BaseModel):
    """A user-confirmed job description captured from a web page."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    capture_uuid: UUID = Field(default_factory=uuid4)
    source_url: HttpUrl
    page_title: NonEmptyText | None = None
    captured_at: AwareDatetime
    capture_method: Literal["page", "selection", "paste"]
    jd_text: NonEmptyText