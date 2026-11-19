"""Build saved-job match summaries without model calls."""

from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from job_application_assistant.job_capture_storage import list_captures
from job_application_assistant.job_requirements_storage import (
    load_requirements
)
from job_application_assistant.profile_match_scoring import (
    score_profile_match
)
from job_application_assistant.profile_match_service import (
    load_saved_profile
)
from job_application_assistant.profile_match_storage import (
    load_profile_match
)
from job_application_assistant.profile_match_validation import (
    profile_revision
)


class MatchSummary(BaseModel):
    """A saved match percentage for one captured job."""

    model_config = ConfigDict(extra="forbid")

    capture_uuid: UUID
    status: Literal[
        "assessed",
        "not_assessed",
        "profile_unavailable"
    ]
    percentage: float | None = None
    missing_evidence_count: int | None = None


def list_match_summaries(
    database: Path,
    profile_path: Path
) -> list[MatchSummary]:
    """Summarize matches against one saved-profile snapshot."""
    captures = list_captures(database)

    if not captures:
        return []

    try:
        profile = load_saved_profile(profile_path)
    except FileNotFoundError:
        return [
            MatchSummary(
                capture_uuid=capture.capture_uuid,
                status="profile_unavailable"
            )
            for capture in captures
        ]

    original_revision = profile_revision(profile)
    summaries = []

    for capture in captures:
        requirements = load_requirements(
            database, capture.capture_uuid
        )

        match = (
            load_profile_match(database, profile, requirements)
            if requirements is not None
            else None
        )

        if match is None:
            summaries.append(
                MatchSummary(
                    capture_uuid=capture.capture_uuid,
                    status="not_assessed"
                )
            )
            continue

        score = score_profile_match(profile, requirements, match)
        summaries.append(
            MatchSummary(
                capture_uuid=capture.capture_uuid,
                status="assessed",
                percentage=score.percentage,
                missing_evidence_count=sum(
                    assessment.classification == "evidence_missing"
                    for assessment in match.assessments
                )
            )
        )

    if (
        profile_revision(load_saved_profile(profile_path))
        != original_revision
    ):
        raise ValueError(
            "The saved profile changed while loading match summaries."
        )

    return summaries