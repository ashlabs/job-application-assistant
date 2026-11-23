"""Apply structured education updates while preserving record identity."""

from typing import Literal

from pydantic import BaseModel, ConfigDict

from job_application_assistant.models import (
    CareerProfile,
    EducationRecord
)


class EducationUpdate(BaseModel):
    """New education facts; null fields preserve existing values."""

    model_config = ConfigDict(extra="forbid")

    existing_education_uuid: str | None
    qualification: str | None
    institution: str | None
    field_of_study: str | None
    status: Literal[
        "completed",
        "in_progress",
        "not_completed",
        "unknown"
    ] | None
    completion_date: str | None


def _normalized(value: str) -> str:
    return " ".join(value.split()).casefold()


def apply_education_update(
    profile: CareerProfile,
    update: EducationUpdate
) -> CareerProfile:
    """Return a validated copy without modifying the input profile."""
    copied = CareerProfile.model_validate(
        profile.model_dump(mode="json")
    )
    changes = update.model_dump(
        exclude={"existing_education_uuid"},
        exclude_none=True
    )

    for value in changes.values():
        if isinstance(value, str) and not value.strip():
            raise ValueError("Education details cannot be blank.")

    existing = None

    if update.existing_education_uuid is not None:
        existing = next(
            (
                record
                for record in copied.education
                if str(record.education_uuid)
                == update.existing_education_uuid
            ),
            None
        )
        if existing is None:
            raise ValueError("Selected education record is missing.")
    else:
        if update.qualification is None:
            raise ValueError(
                "Identify the education record or supply a qualification."
            )

        candidates = [
            record
            for record in copied.education
            if (
                _normalized(record.qualification)
                == _normalized(update.qualification)
                and (
                    update.institution is None
                    or record.institution is None
                    or _normalized(record.institution)
                    == _normalized(update.institution)
                )
            )
        ]

        if len(candidates) > 1:
            raise ValueError("Clarify which education record to update.")
        if candidates:
            existing = candidates[0]

    data = (
        existing.model_dump(mode="json")
        if existing is not None
        else {}
    )
    data.update(changes)

    # Actual completion dates cannot describe unfinished study.
    if data.get("status", "unknown") != "completed":
        if update.completion_date is not None:
            raise ValueError(
                "A completion date requires completed education."
            )
        data["completion_date"] = None

    validated = EducationRecord.model_validate(data)

    for index, record in enumerate(copied.education):
        if record.education_uuid == validated.education_uuid:
            copied.education[index] = validated
            break
    else:
        copied.education.append(validated)

    return CareerProfile.model_validate(copied.model_dump(mode="json"))