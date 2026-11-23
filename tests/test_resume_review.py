"""Verify exact-file approval and rejection of changed sources."""

import json
from uuid import uuid4

import pytest

from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.models import CareerProfile, EducationRecord
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision,
)
from job_application_assistant.resume_draft import (
    ResumeSelection,
    render_resume,
)
from job_application_assistant.resume_review import (
    approve_draft,
    review_draft,
    verify_approval,
)


@pytest.fixture
def draft_case(tmp_path):
    record = EducationRecord(
        qualification="Bachelor of Science",
        status="completed",
        completion_date="2011",
    )
    profile = CareerProfile(education=[record])
    requirements = JobRequirements(
        capture_uuid=uuid4(),
        jd_text_sha256="a" * 64,
    )
    selection = ResumeSelection(
        role_ids=[],
        story_ids=[],
        education_ids=[str(record.education_uuid)],
    )
    manifest = {
        "status": "draft_requires_review",
        "capture_uuid": str(requirements.capture_uuid),
        "profile_sha256": profile_revision(profile),
        "requirements_sha256": requirements_revision(requirements),
        "selection": selection.model_dump(mode="json"),
        "approved_source_snapshot": profile.model_dump(mode="json"),
        "requirements_snapshot": requirements.model_dump(mode="json"),
    }
    (tmp_path / "resume.txt").write_text(
        render_resume(profile, selection, "Example Candidate"),
        encoding="utf-8",
    )
    (tmp_path / "evidence.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    return tmp_path, profile, requirements


def test_unapproved_draft_is_rejected(draft_case):
    directory, profile, requirements = draft_case
    with pytest.raises(ValueError, match="not been approved"):
        verify_approval(directory, profile, requirements)


def test_exact_draft_can_be_approved_and_verified(draft_case):
    directory, profile, requirements = draft_case
    review = review_draft(directory, profile, requirements)
    approve_draft(
        directory, profile, requirements, review["review_token"]
    )
    assert verify_approval(directory, profile, requirements) == (
        review["text"]
    )


def test_changed_files_cannot_use_old_review_token(draft_case):
    directory, profile, requirements = draft_case
    review = review_draft(directory, profile, requirements)
    path = directory / "evidence.json"
    path.write_bytes(path.read_bytes() + b"\n")

    with pytest.raises(ValueError, match="reviewed files changed"):
        approve_draft(
            directory, profile, requirements, review["review_token"]
        )
    assert not (directory / "approval.json").exists()


@pytest.mark.parametrize(
    "change", ["resume", "evidence", "profile", "requirements"]
)
def test_changes_invalidate_approval(draft_case, change):
    directory, profile, requirements = draft_case
    review = review_draft(directory, profile, requirements)
    approve_draft(
        directory, profile, requirements, review["review_token"]
    )

    if change == "resume":
        path = directory / "resume.txt"
        path.write_bytes(path.read_bytes() + b"Unsupported claim.\n")
    elif change == "evidence":
        path = directory / "evidence.json"
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "profile":
        profile = profile.model_copy(deep=True)
        profile.education[0].completion_date = "2012"
    else:
        requirements = requirements.model_copy(deep=True)
        requirements.job_title = "Changed target role"

    with pytest.raises(ValueError):
        verify_approval(directory, profile, requirements)