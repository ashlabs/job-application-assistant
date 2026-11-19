"""Run persistent interview coaching from a generated guide."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from dotenv import dotenv_values
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver

from job_application_assistant.interview_coaching import (
    DIMENSIONS,
    apply_coaching_command,
    build_coaching_graph,
    create_coaching_step,
    new_coaching_state,
)
from job_application_assistant.interview_guide import (
    InterviewGuide,
    validate_guide,
)
from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision,
)
from job_application_assistant.resume_draft import ROOT


HELP = """
Type a practice answer when a question is shown.
/next     Move on after feedback.
/retry    Try the main question again after feedback.
/skip     Skip the current question or remaining follow-up.
/pause    Pause this session.
/resume   Resume this session.
/history  Show all saved answers and feedback.
/quit     Exit while preserving progress.

Ratings are practice feedback, not hiring predictions.
New career claims remain unapproved and never update your profile.
"""


def display_state(state):
    """Show the current question and latest feedback."""
    print(f"\nStatus: {state['status']}")
    if state["last_error"]:
        print(state["last_error"])
    if state["status"] == "complete":
        print("Five-question session complete. Use /history or /quit.")
        return
    print(
        f"Question {state['index'] + 1}/5: "
        f"{state['questions'][state['index']]}"
    )
    evaluated = [
        item
        for item in state["history"]
        if item["event"] == "evaluated"
        and item["question_number"] == state["index"] + 1
    ]
    if evaluated:
        feedback = evaluated[-1]["feedback"]
        for dimension in DIMENSIONS:
            item = feedback[dimension]
            print(
                f"{dimension.title()} {item['score']}/5: "
                f"{item['explanation']}"
            )
        print("Suggestions:")
        for suggestion in feedback["suggestions"]:
            print(f"- {suggestion}")
    if state["phase"] == "followup":
        print(f"\nFollow-up: {state['followup_question']}")
    elif state["phase"] == "review":
        print("\nUse /retry, /next, or /skip.")
    print(f"Model requests for this question: {state['request_count']}/4")


def main():
    """Start or restore a coaching session pinned to its guide snapshot."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guide", type=Path, required=True)
    parser.add_argument("--session", required=True)
    args = parser.parse_args()

    guide_bytes = args.guide.read_bytes()
    manifest = json.loads(guide_bytes)
    profile = CareerProfile.model_validate(manifest["profile_snapshot"])
    requirements = JobRequirements.model_validate(
        manifest["requirements_snapshot"]
    )
    if (
        profile_revision(profile) != manifest["profile_sha256"]
        or requirements_revision(requirements)
        != manifest["requirements_sha256"]
    ):
        raise ValueError("Guide snapshot hashes do not match.")
    guide = validate_guide(
        InterviewGuide.model_validate(manifest["guide"]),
        profile,
        requirements,
        manifest["sources_snapshot"],
    )
    guide_hash = sha256(guide_bytes).hexdigest()

    settings = dotenv_values(ROOT / ".env")
    key = (settings.get("OPENAI_API_KEY") or "").strip()
    model = (settings.get("OPENAI_MODEL") or "").strip()
    if not key or not model:
        raise ValueError("Configure OPENAI_API_KEY and OPENAI_MODEL.")
    llm = ChatOpenAI(
        model=model,
        api_key=key,
        base_url="https://api.openai.com/v1",
        use_responses_api=True,
        timeout=60,
        max_retries=0,
        max_tokens=4096,
    )

    runtime = ROOT / "runtime"
    runtime.mkdir(exist_ok=True)
    guide_key = sha256(
        str(args.guide.resolve()).encode("utf-8")
    ).hexdigest()[:16]
    config = {
        "configurable": {
            "thread_id": f"{guide_key}:{args.session}"
        }
    }
    with SqliteSaver.from_conn_string(
        str(runtime / "coaching_sessions.sqlite")
    ) as saver:
        graph = build_coaching_graph(
            create_coaching_step(llm), saver
        )

        def update(changes):
            graph.update_state(config, changes, as_node="coach")

        state = graph.get_state(config).values
        if not state:
            update(
                new_coaching_state(
                    [item.question for item in guide.practice_questions],
                    profile.model_dump(mode="json"),
                    guide_hash,
                )
            )
        elif state["guide_sha256"] != guide_hash:
            raise ValueError(
                "Guide changed. Use a new session name for the new guide."
            )

        print(HELP)
        print("This session uses the profile snapshot saved in the guide.")
        display_state(graph.get_state(config).values)

        while True:
            entry = input("\nYou: ").strip()
            if not entry:
                continue
            if entry == "/quit":
                print("Session preserved.")
                break
            state = graph.get_state(config).values
            try:
                if entry == "/history":
                    print(json.dumps(
                        state["history"], indent=2, ensure_ascii=False
                    ))
                    continue
                if entry.startswith("/"):
                    changes = apply_coaching_command(state, entry)
                    update(changes)
                else:
                    graph.invoke({"response": entry}, config)
                display_state(graph.get_state(config).values)
            except (ValueError, OSError) as error:
                print(f"Action could not be completed: {error}")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print("\nExited. Completed checkpoints remain saved.")