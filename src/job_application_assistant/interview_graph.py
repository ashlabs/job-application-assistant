"""Graph execution for experience interview."""

from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from job_application_assistant.interview_state import InterviewState
from job_application_assistant.models import CareerProfile

InterviewStep = Callable[[InterviewState], dict[str, Any]]

def validate_draft(state: InterviewState) -> dict[str, Any]:
    """Validate career records before the interview step uses them."""
    try:
        profile = CareerProfile.model_validate(state["draft_profile"])
    except ValidationError:
        return {
            "status": "error",
            "last_error": (
                "The draft profile is invalid. Correct its records "
                "before continuing."
            )
        }

    return {"draft_profile": profile.model_dump(mode="json")}


def route_after_validation(state: InterviewState) -> str:
    """Only an actively collecting session may run an interview turn."""
    if state["status"] == "collecting":
        return "interview"

    return "stop"


def build_interview_graph(
    interview_step: InterviewStep,
    checkpointer: BaseCheckpointSaver
):
    """Build one interview turn with checkpointed state."""
    builder = StateGraph(InterviewState)

    builder.add_node("validate_draft", validate_draft)
    builder.add_node("interview", interview_step)

    builder.add_edge(START, "validate_draft")
    builder.add_conditional_edges(
        "validate_draft",
        route_after_validation,
        {
            "interview": "interview",
            "stop": END
        }
    )
    builder.add_edge("interview", END)

    return builder.compile(checkpointer=checkpointer)