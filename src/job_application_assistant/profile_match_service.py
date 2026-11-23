"""Assess saved career profiles against extracted job requirements."""

from collections.abc import Callable
from pathlib import Path

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict

from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_markdown import profile_from_markdown
from job_application_assistant.profile_match import ProfileMatch
from job_application_assistant.profile_match_agent import (
    create_profile_match_assessor,
)
from job_application_assistant.profile_match_scoring import (
    DocumentedMatchScore,
    score_profile_match
)
from job_application_assistant.profile_match_validation import (
    profile_revision
)
from job_application_assistant.profile_match_storage import (
    load_profile_match,
    save_profile_match
)


ROOT = Path(__file__).resolve().parents[2]

ProfileAssessor = Callable[
    [CareerProfile, JobRequirements],
    ProfileMatch
]


class MatchConfigurationError(RuntimeError):
    """Required model settings are missing."""


class ProfileMatchReport(BaseModel):
    """Validated assessments and their Python-calculated score."""

    model_config = ConfigDict(extra="forbid")

    match: ProfileMatch
    score: DocumentedMatchScore


def load_saved_profile(profile_path: Path) -> CareerProfile:
    """Read the saved Markdown profile, never an interview-session draft."""
    markdown = profile_path.read_bytes().decode("utf-8")
    return profile_from_markdown(markdown)


def assess_saved_profile(
    profile_path: Path,
    requirements: JobRequirements,
    *,
    assessor: ProfileAssessor | None = None
) -> ProfileMatchReport:
    """Assess the saved profile and reject changes made during assessment."""
    profile = load_saved_profile(profile_path)
    original_revision = profile_revision(profile)

    source = JobRequirements.model_validate(
        requirements.model_dump(mode="json")
    )

    if assessor is None:
        settings = dotenv_values(ROOT / ".env")
        api_key = (settings.get("OPENAI_API_KEY") or "").strip()
        model = (settings.get("OPENAI_MODEL") or "").strip()

        if not api_key or not model:
            raise MatchConfigurationError(
                "Set OPENAI_API_KEY and OPENAI_MODEL in .env."
            )

        llm = ChatOpenAI(
            model=model,
            api_key=api_key,
            base_url="https://api.openai.com/v1",
            use_responses_api=True,
            timeout=60,
            max_retries=0,
            max_tokens=4096
        )
        assessor = create_profile_match_assessor(llm)

    match = assessor(profile, source)
    score = score_profile_match(profile, source, match)

    current_profile = load_saved_profile(profile_path)
    if profile_revision(current_profile) != original_revision:
        raise ValueError(
            "The saved profile changed during assessment. Assess it again."
        )

    return ProfileMatchReport(
        match=match,
        score=score
    )

def load_saved_match_report(
    database: Path,
    profile_path: Path,
    requirements: JobRequirements
) -> ProfileMatchReport | None:
    """Load a report for the current saved profile and requirements."""
    profile = load_saved_profile(profile_path)
    original_revision = profile_revision(profile)

    match = load_profile_match(database, profile, requirements)

    if match is None:
        return None

    score = score_profile_match(profile, requirements, match)

    if (
        profile_revision(load_saved_profile(profile_path))
        != original_revision
    ):
        raise ValueError(
            "The saved profile changed while loading the report."
        )

    return ProfileMatchReport(match=match, score=score)


def save_match_report(
    database: Path,
    profile_path: Path,
    requirements: JobRequirements,
    report: ProfileMatchReport
) -> ProfileMatchReport:
    """Validate against the saved profile before storing a match."""
    profile = load_saved_profile(profile_path)

    # Validate sources and evidence; never trust a supplied score.
    score_profile_match(profile, requirements, report.match)

    saved_match = save_profile_match(
        database,
        profile,
        requirements,
        report.match
    )

    score = score_profile_match(profile, requirements, saved_match)

    if (
        profile_revision(load_saved_profile(profile_path))
        != saved_match.profile_sha256
    ):
        raise ValueError(
            "The saved profile changed while saving the report. "
            "Assess it again."
        )

    return ProfileMatchReport(match=saved_match, score=score)