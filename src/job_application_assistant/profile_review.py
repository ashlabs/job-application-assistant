"""Prepare career-profile changes for user review."""

from dataclasses import dataclass
from difflib import unified_diff
from hashlib import sha256
from uuid import UUID, uuid4

from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_markdown import (
    profile_from_markdown,
    profile_to_markdown,
)


def content_revision(markdown: str) -> str:
    """Identify an exact version of the Markdown content."""
    return sha256(markdown.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProfileProposal:
    """An immutable snapshot awaiting user approval."""

    proposal_uuid: UUID
    base_revision: str | None
    proposed_markdown: str
    diff: str


def prepare_profile_proposal(
    current_markdown: str | None,
    proposed_profile: CareerProfile,
) -> ProfileProposal:
    """Validate both versions and capture their differences."""
    if current_markdown is not None:
        profile_from_markdown(current_markdown)

    proposed_markdown = profile_to_markdown(proposed_profile)

    if current_markdown == proposed_markdown:
        raise ValueError("The proposed profile contains no changes.")

    diff = "".join(
        unified_diff(
            (current_markdown or "").splitlines(keepends=True),
            proposed_markdown.splitlines(keepends=True),
            fromfile="current/career_profile.md",
            tofile="proposed/career_profile.md",
        )
    )

    return ProfileProposal(
        proposal_uuid=uuid4(),
        base_revision=(
            content_revision(current_markdown)
            if current_markdown is not None
            else None
        ),
        proposed_markdown=proposed_markdown,
        diff=diff,
    )
