"""Session state for the experience interview workflow."""

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages

from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_markdown import profile_from_markdown


class ProposalSnapshot(TypedDict):
    """Serializable copy of a proposal awaiting review."""

    proposal_uuid: str
    base_revision: str | None
    proposed_markdown: str
    diff: str


class InterviewState(TypedDict):
    """Information carried between interview steps."""

    messages: Annotated[list[AnyMessage], add_messages]
    current_markdown: str | None
    draft_profile: dict[str, Any]
    active_story_uuid: str | None
    skipped_topics: list[str]
    pending_proposal: ProposalSnapshot | None
    status: Literal[
        "collecting",
        "awaiting_review",
        "paused",
        "saved",
        "error"
    ]
    turn_count: int
    last_error: str | None


def new_interview_state(
    current_markdown: str | None = None,
) -> InterviewState:
    """Start a session from an existing profile or an empty draft."""
    profile = (
        profile_from_markdown(current_markdown)
        if current_markdown is not None
        else CareerProfile()
    )

    return {
        "messages": [],
        "current_markdown": current_markdown,
        "draft_profile": profile.model_dump(mode="json"),
        "active_story_uuid": None,
        "skipped_topics": [],
        "pending_proposal": None,
        "status": "collecting",
        "turn_count": 0,
        "last_error": None
    }