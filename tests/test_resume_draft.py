"""Check factual rendering and rejection of invalid resume selections."""

from uuid import uuid4

import pytest

from job_application_assistant.models import (
    CareerProfile,
    EducationRecord,
    EmploymentRecord,
    ExperienceStory,
)
from job_application_assistant.resume_draft import (
    ResumeSelection,
    render_resume,
    select_resume_records,
    validate_selection,
)


@pytest.fixture
def resume_case():
    role = EmploymentRecord(
        employer="Example Company",
        job_title="Engineering Manager",
        start_date="2018-01",
        end_date="2022-12",
        is_current=False,
    )
    story = ExperienceStory(
        role_uuid=role.role_uuid,
        title="Service reliability",
        action="Coached six engineers and led delivery reviews.",
    )
    education = EducationRecord(
        qualification="Master of Science",
        field_of_study="Artificial Intelligence",
        status="in_progress",
    )
    profile = CareerProfile(
        roles=[role], stories=[story], education=[education]
    )
    selection = ResumeSelection(
        role_ids=[str(role.role_uuid)],
        story_ids=[str(story.story_uuid)],
        education_ids=[str(education.education_uuid)],
    )
    return profile, selection


def test_resume_preserves_facts_and_ongoing_education(resume_case):
    profile, selection = resume_case
    original = profile.model_dump(mode="json")

    text = render_resume(profile, selection, "Example Candidate")

    assert "Engineering Manager | Example Company" in text
    assert "2018-01 – 2022-12" in text
    assert "Coached six engineers and led delivery reviews." in text
    assert "In progress" in text
    assert "Completed" not in text
    assert "Result:" not in text
    assert profile.model_dump(mode="json") == original


@pytest.mark.parametrize("problem", ["unknown", "duplicate", "unlinked"])
def test_invalid_resume_selection_is_rejected(resume_case, problem):
    profile, selection = resume_case
    selection = selection.model_copy(deep=True)

    if problem == "unknown":
        selection.role_ids = [str(uuid4())]
    elif problem == "duplicate":
        selection.story_ids *= 2
    else:
        selection.role_ids = []

    with pytest.raises(ValueError):
        validate_selection(profile, selection)


def test_model_selection_cannot_introduce_unknown_records(resume_case):
    from job_application_assistant.job_requirements import JobRequirements

    profile, selection = resume_case
    selection.education_ids = [str(uuid4())]

    class FakeModel:
        def with_structured_output(self, schema, **kwargs):
            assert schema is ResumeSelection
            return self

        def invoke(self, messages):
            return selection

    requirements = JobRequirements(
        capture_uuid=uuid4(),
        jd_text_sha256="a" * 64,
    )
    with pytest.raises(ValueError, match="Unknown"):
        select_resume_records(FakeModel(), profile, requirements)