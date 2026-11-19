"""Regression tests for interview draft updates."""

from uuid import uuid4

from langchain_core.messages import HumanMessage

from job_application_assistant.interview_agent import (
    StoryTurn,
    create_interview_step,
)
from job_application_assistant.interview_state import new_interview_state
from job_application_assistant.models import (
    CareerProfile,
    EmploymentRecord,
    ExperienceStory,
)
from job_application_assistant.profile_markdown import profile_to_markdown


class FakeModel:
    """Return a predetermined structured response."""

    def __init__(self, response):
        self.response = response

    def with_structured_output(self, schema, **kwargs):
        assert schema is StoryTurn
        return self

    def invoke(self, messages):
        return self.response


def make_turn(**updates):
    """Build a complete response with unknown fields left null."""
    data = {
        name: None
        for name in StoryTurn.model_fields
    }
    data["next_question"] = "What happened after your actions?"
    data.update(updates)
    return StoryTurn.model_validate(data)


def make_saved_profile():
    """Create a profile containing one role and one story."""
    role = EmploymentRecord(
        employer="Example Company",
        job_title="Product Manager",
    )
    story = ExperienceStory(
        role_uuid=role.role_uuid,
        title="Improving account setup",
        action="Interviewed customers and simplified account setup.",
    )
    return CareerProfile(roles=[role], stories=[story])


def test_new_story_reuses_role_and_preserves_existing_story():
    profile = make_saved_profile()
    original = profile.model_dump(mode="json")
    state = new_interview_state(profile_to_markdown(profile))
    state["messages"] = [
        HumanMessage(
            content=(
                "As a Product Manager at Example Company, "
                "I led a separate prioritization workshop."
            )
        )
    ]

    turn = make_turn(
        employer=" example company ",
        job_title="product manager",
        title="Improving feature prioritization",
        action="Led a prioritization workshop.",
    )
    result = create_interview_step(FakeModel(turn))(state)
    updated = CareerProfile.model_validate(result["draft_profile"])

    assert len(updated.roles) == 1
    assert len(updated.stories) == 2
    assert updated.roles[0].role_uuid == profile.roles[0].role_uuid
    assert updated.stories[0] == profile.stories[0]
    assert updated.stories[1].story_uuid != profile.stories[0].story_uuid
    assert updated.stories[1].role_uuid == profile.roles[0].role_uuid
    assert updated.stories[1].result is None
    assert updated.stories[1].reflection is None
    assert state["draft_profile"] == original
    assert result["pending_proposal"] is None


def test_correction_preserves_story_identity_and_role_link():
    profile = make_saved_profile()
    state = new_interview_state(profile_to_markdown(profile))
    state["active_story_uuid"] = str(profile.stories[0].story_uuid)
    state["messages"] = [
        HumanMessage(
            content="My assigned task was to improve setup completion."
        )
    ]

    turn = make_turn(
        task="Improve setup completion.",
    )
    result = create_interview_step(FakeModel(turn))(state)
    updated = CareerProfile.model_validate(result["draft_profile"])
    story = updated.stories[0]

    assert len(updated.roles) == 1
    assert len(updated.stories) == 1
    assert story.story_uuid == profile.stories[0].story_uuid
    assert story.role_uuid == profile.roles[0].role_uuid
    assert story.task == "Improve setup completion."
    assert story.action == profile.stories[0].action
    assert story.result is None


def test_unknown_role_reference_leaves_draft_unchanged():
    profile = make_saved_profile()
    state = new_interview_state(profile_to_markdown(profile))
    original = profile.model_dump(mode="json")
    state["messages"] = [
        HumanMessage(content="I led another initiative.")
    ]

    turn = make_turn(
        existing_role_uuid=str(uuid4()),
        title="Another initiative",
        action="Led a workshop.",
    )
    result = create_interview_step(FakeModel(turn))(state)

    assert result["status"] == "error"
    assert "draft_profile" not in result
    assert state["draft_profile"] == original
    assert state["active_story_uuid"] is None

def test_date_only_answer_preserves_story_and_role_identity():
    profile = make_saved_profile()
    state = new_interview_state(profile_to_markdown(profile))
    state["active_story_uuid"] = str(profile.stories[0].story_uuid)
    state["messages"] = [
        HumanMessage(
            content="I held that role from March 2018 to July 2023."
        )
    ]
    original = profile.model_dump(mode="json")

    turn = make_turn(
        start_date="2018-03",
        end_date="2023-07",
        is_current=False,
    )
    result = create_interview_step(FakeModel(turn))(state)
    updated = CareerProfile.model_validate(result["draft_profile"])

    assert len(updated.roles) == 1
    assert updated.roles[0].role_uuid == profile.roles[0].role_uuid
    assert updated.roles[0].start_date == "2018-03"
    assert updated.roles[0].end_date == "2023-07"
    assert updated.roles[0].is_current is False
    assert updated.stories == profile.stories
    assert state["draft_profile"] == original


def test_role_dates_can_update_without_creating_story():
    profile = make_saved_profile()
    state = new_interview_state(profile_to_markdown(profile))
    state["messages"] = [
        HumanMessage(
            content="That Product Manager role started in 2018. "
            "I still hold it."
        )
    ]

    turn = make_turn(
        existing_role_uuid=str(profile.roles[0].role_uuid),
        start_date="2018",
        is_current=True,
    )
    result = create_interview_step(FakeModel(turn))(state)
    updated = CareerProfile.model_validate(result["draft_profile"])

    assert updated.roles[0].start_date == "2018"
    assert updated.roles[0].end_date is None
    assert updated.roles[0].is_current is True
    assert updated.stories == profile.stories
    assert result["active_story_uuid"] is None


def test_current_role_correction_clears_previous_end_date():
    profile = make_saved_profile()
    profile.roles[0].start_date = "2018"
    profile.roles[0].end_date = "2023"
    profile.roles[0].is_current = False
    state = new_interview_state(profile_to_markdown(profile))
    state["active_story_uuid"] = str(profile.stories[0].story_uuid)
    state["messages"] = [
        HumanMessage(
            content="Correction: I still hold that role."
        )
    ]

    result = create_interview_step(
        FakeModel(make_turn(is_current=True))
    )(state)
    updated = CareerProfile.model_validate(result["draft_profile"])

    assert updated.roles[0].start_date == "2018"
    assert updated.roles[0].end_date is None
    assert updated.roles[0].is_current is True
    assert updated.stories == profile.stories


def test_contradictory_current_role_dates_leave_draft_unchanged():
    profile = make_saved_profile()
    state = new_interview_state(profile_to_markdown(profile))
    state["active_story_uuid"] = str(profile.stories[0].story_uuid)
    original = profile.model_dump(mode="json")

    turn = make_turn(
        is_current=True,
        end_date="2023"
    )
    result = create_interview_step(FakeModel(turn))(state)

    assert result["status"] == "error"
    assert "draft_profile" not in result
    assert state["draft_profile"] == original