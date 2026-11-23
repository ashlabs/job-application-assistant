"""Tests for profile review, approval, and conflicting saves."""

from uuid import UUID, uuid4

import pytest

from job_application_assistant.interview_review import (
    approve_interview_review,
    prepare_interview_review,
)
from job_application_assistant.interview_state import new_interview_state
from job_application_assistant.models import CareerProfile, ExperienceStory
from job_application_assistant.profile_markdown import (
    profile_from_markdown,
    profile_to_markdown
)
from job_application_assistant.profile_review import content_revision
from job_application_assistant.profile_storage import ProfileConflictError


def make_review(current_markdown=None, title="Customer onboarding"):
    """Prepare a reviewable draft without writing any files."""
    state = new_interview_state(current_markdown)
    profile = CareerProfile.model_validate(state["draft_profile"])
    data = profile.model_dump(mode="json")
    data["stories"].append(
        ExperienceStory(
            title=title,
            action="Interviewed customers.",
        ).model_dump(mode="json")
    )
    state["draft_profile"] = data
    state.update(prepare_interview_review(state))
    return state


def approve(state, directory):
    """Approve the exact pending proposal."""
    return approve_interview_review(
        state,
        directory,
        approved_proposal_uuid=UUID(
            state["pending_proposal"]["proposal_uuid"]
        )
    )


def test_preparing_review_does_not_save_profile(tmp_path):
    state = make_review()

    assert state["status"] == "awaiting_review"
    assert state["pending_proposal"] is not None
    assert list(tmp_path.iterdir()) == []


def test_saving_requires_a_pending_review(tmp_path):
    state = new_interview_state()

    with pytest.raises(ValueError, match="No proposal"):
        approve_interview_review(
            state,
            tmp_path,
            approved_proposal_uuid=uuid4()
        )

    assert list(tmp_path.iterdir()) == []


def test_wrong_approval_identifier_does_not_write_files(tmp_path):
    state = make_review()

    with pytest.raises(PermissionError, match="does not match"):
        approve_interview_review(
            state,
            tmp_path,
            approved_proposal_uuid=uuid4()
        )

    assert list(tmp_path.iterdir()) == []


def test_changed_draft_requires_another_review(tmp_path):
    state = make_review()
    state["draft_profile"]["stories"][0]["action"] = (
        "Interviewed customers and reviewed support tickets."
    )

    with pytest.raises(ValueError, match="draft changed"):
        approve(state, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_approval_saves_exact_snapshot_and_allows_retry(tmp_path):
    state = make_review()
    expected = state["pending_proposal"]["proposed_markdown"]

    result = approve(state, tmp_path)
    profile_path = tmp_path / "career_profile.md"

    assert profile_path.read_bytes().decode("utf-8") == expected
    assert profile_from_markdown(expected).model_dump(mode="json") == (
        state["draft_profile"]
    )
    assert result["status"] == "saved"
    assert result["pending_proposal"] is None
    assert result["current_markdown"] == expected

    # Simulate retrying after the file was saved but before the
    # caller persisted the returned session state.
    retry = approve(state, tmp_path)

    assert retry == result
    assert profile_path.read_bytes().decode("utf-8") == expected
    assert not (tmp_path / "history").exists()


def test_stale_proposal_cannot_overwrite_a_newer_save(tmp_path):
    initial = make_review()
    saved = approve(initial, tmp_path)
    original_markdown = saved["current_markdown"]

    first = make_review(
        original_markdown,
        title="Feature prioritization"
    )
    stale = make_review(
        original_markdown,
        title="Another initiative"
    )

    first_result = approve(first, tmp_path)
    expected = first_result["current_markdown"]

    with pytest.raises(ProfileConflictError, match="profile changed"):
        approve(stale, tmp_path)

    profile_path = tmp_path / "career_profile.md"
    assert profile_path.read_bytes().decode("utf-8") == expected

    history_path = (
        tmp_path
        / "history"
        / f"{content_revision(original_markdown)}.md"
    )
    assert history_path.read_bytes().decode("utf-8") == (
        original_markdown
    )
    assert profile_to_markdown(
        profile_from_markdown(expected)
    ) == expected
