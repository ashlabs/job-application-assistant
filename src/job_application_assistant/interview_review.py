"""User-controlled review and approval of interview drafts."""

from pathlib import Path
from uuid import UUID

from job_application_assistant.interview_state import InterviewState
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_markdown import (
    profile_from_markdown,
    profile_to_markdown
)
from job_application_assistant.profile_review import (
    ProfileProposal,
    prepare_profile_proposal
)
from job_application_assistant.profile_storage import save_approved_proposal


def prepare_interview_review(state: InterviewState) -> dict:
    """Capture the current draft as a proposal awaiting review."""
    if state["status"] not in {"collecting", "paused"}:
        raise ValueError("This session cannot enter review now.")

    profile = CareerProfile.model_validate(state["draft_profile"])
    proposal = prepare_profile_proposal(
        state["current_markdown"],
        profile
    )

    return {
        "pending_proposal": {
            "proposal_uuid": str(proposal.proposal_uuid),
            "base_revision": proposal.base_revision,
            "proposed_markdown": proposal.proposed_markdown,
            "diff": proposal.diff,
        },
        "status": "awaiting_review",
        "last_error": None
    }


def approve_interview_review(
    state: InterviewState,
    directory: Path,
    *,
    approved_proposal_uuid: UUID
) -> dict:
    """Save the proposal explicitly approved through the interface."""
    pending = state["pending_proposal"]

    if state["status"] != "awaiting_review" or pending is None:
        raise ValueError("No proposal is awaiting review.")

    proposal = ProfileProposal(
        proposal_uuid=UUID(pending["proposal_uuid"]),
        base_revision=pending["base_revision"],
        proposed_markdown=pending["proposed_markdown"],
        diff=pending["diff"]
    )

    if approved_proposal_uuid != proposal.proposal_uuid:
        raise PermissionError("Approval does not match the pending proposal.")

    draft = CareerProfile.model_validate(state["draft_profile"])
    if profile_to_markdown(draft) != proposal.proposed_markdown:
        raise ValueError(
            "The draft changed after review was prepared. Review it again."
        )

    save_approved_proposal(
        directory,
        proposal,
        approved_proposal_uuid=approved_proposal_uuid
    )

    saved_profile = profile_from_markdown(proposal.proposed_markdown)

    return {
        "current_markdown": proposal.proposed_markdown,
        "draft_profile": saved_profile.model_dump(mode="json"),
        "pending_proposal": None,
        "status": "saved",
        "last_error": None
    }