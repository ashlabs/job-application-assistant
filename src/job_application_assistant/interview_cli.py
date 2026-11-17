"""Run a persistent career experience interview from the terminal."""

import argparse
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Overwrite

from job_application_assistant.interview_agent import create_interview_step
from job_application_assistant.interview_graph import build_interview_graph
from job_application_assistant.interview_review import (
    approve_interview_review,
    prepare_interview_review,
)
from job_application_assistant.interview_state import new_interview_state
from job_application_assistant.models import CareerProfile


ROOT = Path(__file__).resolve().parents[2]

OPENING_QUESTION = (
    "Describe one initiative you led and what you personally did."
)

HELP = """
Type an answer to continue the interview.

Commands:
  /new            Start another story while preserving the current draft.
  /draft          Show the current draft profile.
  /review         Prepare a proposal and show its changes.
  /approve UUID   Approve the proposal with the displayed UUID.
  /edit           Return from review to the interview.
  /pause          Pause the interview.
  /resume         Resume a paused interview or retry after an error.
  /restart        Discard this interview and restart from the saved profile.
  /quit           Exit while preserving the session.
"""


def main() -> None:
    """Start or restore an interview session."""
    parser = argparse.ArgumentParser(
        description="Capture career experience through an interview."
    )
    parser.add_argument(
        "--session",
        required=True,
        help="A session name used to save and restore this interview."
    )
    parser.add_argument(
        "--profile-dir",
        default="data/private/profile",
        help="Directory containing the approved career profile."
    )
    args = parser.parse_args()

    directory = (ROOT / args.profile_dir).resolve()
    profile_path = directory / "career_profile.md"

    settings = dotenv_values(ROOT / ".env")
    api_key = (settings.get("OPENAI_API_KEY") or "").strip()
    model = (settings.get("OPENAI_MODEL") or "").strip()

    if not api_key or not model:
        raise SystemExit(
            "Set OPENAI_API_KEY and OPENAI_MODEL in the project's .env file."
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

    runtime = ROOT / "runtime"
    runtime.mkdir(exist_ok=True)

    profile_key = sha256(str(directory).encode("utf-8")).hexdigest()[:16]
    config = {
        "configurable": {
            "thread_id": f"{profile_key}:{args.session}"
        }
    }

    with SqliteSaver.from_conn_string(
        str(runtime / "experience_sessions.sqlite")
    ) as saver:
        graph = build_interview_graph(
            create_interview_step(llm),
            saver
        )

        def update(changes: dict) -> None:
            """Persist a command's state changes without calling the model."""
            graph.update_state(
                config,
                changes,
                as_node="interview"
            )

        state = graph.get_state(config).values

        if not state:
            current = (
                profile_path.read_bytes().decode("utf-8")
                if profile_path.exists()
                else None
            )
            update(new_interview_state(current))
            print(f"\nAssistant: {OPENING_QUESTION}")
        else:
            print(f"\nRestored session: {args.session}")
            print(f"Status: {state['status']}")

            if state.get("last_error"):
                print(state["last_error"])

            if state.get("messages"):
                last_message = state["messages"][-1]
                print(f"\nLast message: {last_message.content}")

            pending = state.get("pending_proposal")
            if pending is not None:
                print("\nPending proposal:")
                print(pending["diff"])
                print(f"Proposal UUID: {pending['proposal_uuid']}")

        print(HELP)

        while True:
            state = graph.get_state(config).values
            entry = input("\nYou: ").strip()

            if not entry:
                continue

            try:
                if entry == "/quit":
                    print("Session preserved.")
                    break

                if entry == "/restart":
                    confirmation = input(
                        "Discard this conversation and all unapproved "
                        "changes? Type RESTART to confirm: "
                    ).strip()

                    if confirmation != "RESTART":
                        print("Restart cancelled.")
                        continue

                    current = (
                        profile_path.read_bytes().decode("utf-8")
                        if profile_path.exists()
                        else None
                    )

                    fresh_state = dict(new_interview_state(current))
                    fresh_state["messages"] = Overwrite(value=[])
                    update(fresh_state)

                    print(
                        "Interview restarted. Your saved profile "
                        "has been preserved."
                    )
                    print(f"\nAssistant: {OPENING_QUESTION}")
                    continue

                if entry == "/new":
                    update(
                        {
                            "messages": Overwrite(value=[]),
                            "active_story_uuid": None,
                            "skipped_topics": [],
                            "pending_proposal": None,
                            "status": "collecting",
                            "last_error": None,
                        }
                    )
                    print(
                        "Starting another story. All existing draft "
                        "stories and employment records are preserved."
                    )
                    print(
                        "Any pending review has been cancelled. "
                        "Use /review again when ready."
                    )
                    print(f"\nAssistant: {OPENING_QUESTION}")
                    continue

                if entry == "/draft":
                    profile = CareerProfile.model_validate(
                        state["draft_profile"]
                    )
                    print(profile.model_dump_json(indent=2))
                    continue

                if entry == "/review":
                    profile = CareerProfile.model_validate(
                        state["draft_profile"]
                    )

                    if not profile.roles and not profile.stories:
                        print(
                            "Capture some career experience before "
                            "preparing a review."
                        )
                        continue

                    changes = prepare_interview_review(state)
                    update(changes)

                    pending = changes["pending_proposal"]
                    print("\nProposed changes:")
                    print(pending["diff"])
                    print(f"Proposal UUID: {pending['proposal_uuid']}")
                    print(
                        "\nReview the changes carefully. Use "
                        "/approve UUID to save this exact proposal, "
                        "or /edit to make corrections."
                    )
                    continue

                if entry.startswith("/approve"):
                    parts = entry.split()

                    if len(parts) != 2 or parts[0] != "/approve":
                        print("Usage: /approve UUID")
                        continue

                    changes = approve_interview_review(
                        state,
                        directory,
                        approved_proposal_uuid=UUID(parts[1]),
                    )
                    update(changes)

                    print(f"Approved profile saved to: {profile_path}")
                    print(
                        "Use /quit to exit, or /restart to begin "
                        "another interview using the saved profile."
                    )
                    continue

                if entry == "/edit":
                    if state["status"] != "awaiting_review":
                        print("There is no pending review to edit.")
                        continue

                    update(
                        {
                            "status": "collecting",
                            "pending_proposal": None,
                            "last_error": None
                        }
                    )
                    print("Review cancelled. Type your correction.")
                    continue

                if entry == "/pause":
                    if state["status"] != "collecting":
                        print(
                            "Only an active interview can be paused."
                        )
                        continue

                    update({"status": "paused"})
                    print(
                        "Interview paused. Use /resume to continue "
                        "or /quit to exit."
                    )
                    continue

                if entry == "/resume":
                    if state["status"] not in {"paused", "error"}:
                        print(
                            "Use /resume when the interview is paused "
                            "or has encountered an error."
                        )
                        continue

                    update(
                        {
                            "status": "collecting",
                            "last_error": None
                        }
                    )
                    print(
                        "Interview resumed. Type your next answer. "
                        "If the previous turn failed, enter it again."
                    )
                    continue

                if entry.startswith("/"):
                    print(HELP)
                    continue

                if state["status"] != "collecting":
                    print(f"Current status: {state['status']}.")
                    print(
                        "Use /edit during review, /resume after a pause "
                        "or error, or /restart to begin again."
                    )
                    continue

                if state["turn_count"] >= 30:
                    print(
                        "This interview has reached its 30-turn limit. "
                        "Use /review to review the draft, /pause to "
                        "pause, or /restart to begin again."
                    )
                    continue

                result = graph.invoke(
                    {"messages": [HumanMessage(content=entry)]},
                    config
                )

                if result["status"] == "error":
                    print(result["last_error"])
                    print(
                        "Use /resume and enter your answer again, "
                        "or /restart to begin again."
                    )
                else:
                    print(
                        f"\nAssistant: {result['messages'][-1].content}"
                    )

            except (ValueError, OSError) as error:
                print(f"Action could not be completed: {error}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nExited. Completed checkpoints remain saved.")