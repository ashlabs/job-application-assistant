"""Verify coaching bounds, commands, and persistent progress."""

import pytest
from langgraph.checkpoint.sqlite import SqliteSaver
from openai import OpenAIError

from job_application_assistant.interview_coaching import (
    DIMENSIONS,
    CoachingFeedback,
    apply_coaching_command,
    build_coaching_graph,
    create_coaching_step,
    new_coaching_state,
)


def make_feedback(follow_up=None):
    return CoachingFeedback(
        **{
            name: {
                "score": 3,
                "explanation": "The response provides limited detail.",
            }
            for name in DIMENSIONS
        },
        suggestions=["Explain your personal contribution."],
        follow_up=follow_up,
    )


class FakeModel:
    def __init__(self, feedback):
        self.feedback = feedback
        self.calls = 0

    def with_structured_output(self, schema, **kwargs):
        assert schema is CoachingFeedback
        return self

    def invoke(self, messages):
        self.calls += 1
        if isinstance(self.feedback, Exception):
            raise self.feedback
        return self.feedback


@pytest.fixture
def state():
    return new_coaching_state(
        [f"Practice question {index}?" for index in range(5)],
        {"roles": [], "stories": [], "education": []},
        "test-guide",
    )


def test_only_one_followup_per_question_even_after_retry(state):
    model = FakeModel(make_feedback("What did you personally do?"))
    step = create_coaching_step(model)

    state["response"] = "I led weekly delivery reviews."
    state.update(step(state))
    assert state["phase"] == "followup"

    state["response"] = "I assigned responsibilities."
    state.update(step(state))
    assert state["phase"] == "review"
    assert state["followup_question"] is None

    state.update(apply_coaching_command(state, "/retry"))
    state["response"] = "I coached engineers and assigned work."
    state.update(step(state))
    assert state["phase"] == "review"
    assert model.calls == 3


def test_failed_requests_count_toward_limit(state):
    model = FakeModel(OpenAIError("Provider unavailable"))
    step = create_coaching_step(model)
    state["response"] = "My practice answer."

    for _ in range(5):
        state.update(step(state))

    assert model.calls == 4
    assert state["request_count"] == 4
    assert state["history"] == []


def test_pause_blocks_model_requests_and_resume_preserves_question(state):
    model = FakeModel(make_feedback())
    step = create_coaching_step(model)
    state.update(apply_coaching_command(state, "/pause"))
    state["response"] = "My answer."
    state.update(step(state))
    assert model.calls == 0

    state.update(apply_coaching_command(state, "/resume"))
    assert state["index"] == 0
    state.update(step(state))
    assert model.calls == 1


def test_five_skips_complete_session(state):
    for _ in range(5):
        state.update(apply_coaching_command(state, "/skip"))
    assert state["status"] == "complete"
    assert len(state["history"]) == 5
    with pytest.raises(ValueError):
        apply_coaching_command(state, "/skip")


def test_coaching_does_not_change_profile_snapshot(state):
    original = dict(state["profile_snapshot"])
    state["response"] = "I have additional experience not yet approved."
    result = create_coaching_step(
        FakeModel(make_feedback())
    )(state)
    assert "profile_snapshot" not in result
    assert state["profile_snapshot"] == original


def test_checkpoint_survives_reopening(tmp_path, state):
    database = str(tmp_path / "coaching.sqlite")
    config = {"configurable": {"thread_id": "test-session"}}

    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_coaching_graph(
            create_coaching_step(FakeModel(make_feedback())), saver
        )
        graph.update_state(config, state, as_node="coach")
        graph.invoke({"response": "I coached engineers."}, config)
        saved = graph.get_state(config).values

    with SqliteSaver.from_conn_string(database) as saver:
        graph = build_coaching_graph(
            create_coaching_step(FakeModel(make_feedback())), saver
        )
        restored = graph.get_state(config).values

    assert restored == saved
    assert restored["phase"] == "review"
    assert len(restored["history"]) == 1