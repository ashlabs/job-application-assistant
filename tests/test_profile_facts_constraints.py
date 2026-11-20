"""Approval boundary, evidence integrity, and separate constraint credit."""

from uuid import uuid4
import pytest
from pydantic import ValidationError

from job_application_assistant.models import CareerProfile, ProfileFact
from job_application_assistant.fact_capture import FactUpdate, apply_fact_update
from job_application_assistant.profile_markdown import profile_to_markdown, profile_from_markdown
from job_application_assistant.profile_match import ConstraintAssessment, ProfileEvidence, ProfileMatch
from job_application_assistant.profile_match_agent import (
    MatchResponse, ConstraintResponse, EvidenceResponse, create_profile_match_assessor,
)
from job_application_assistant.profile_match_validation import (
    profile_revision, requirements_revision, validate_profile_match,
)
from job_application_assistant.profile_match_scoring import score_profile_match
from job_application_assistant.job_requirements import JobRequirement, JobRequirements
from job_application_assistant.profile_match_storage import save_profile_match, load_profile_match


def update(**values):
    return FactUpdate(existing_fact_uuid=None, category="preference", name="Work mode",
                      statement="I accept only fully remote roles.", **values)


def case():
    profile = apply_fact_update(CareerProfile(), update())
    constraint = JobRequirement(description="Must work onsite in Kirkland.",
        source_excerpt="Must work onsite in Kirkland.", kind="constraint", importance="required")
    requirements = JobRequirements(capture_uuid=uuid4(), jd_text_sha256="a" * 64,
                                   requirements=[constraint])
    fact = profile.facts[0]
    evidence = ProfileEvidence(record_type="fact", record_uuid=fact.fact_uuid,
                              field_name="statement", excerpt=fact.statement)
    match = ProfileMatch(capture_uuid=requirements.capture_uuid,
        profile_sha256=profile_revision(profile), requirements_sha256=requirements_revision(requirements),
        constraints=[ConstraintAssessment(requirement_uuid=constraint.requirement_uuid,
            classification="blocking", explanation="Remote-only conflicts with required onsite work.",
            evidence=[evidence])])
    return profile, requirements, match


def test_facts_roundtrip_and_old_profiles_remain_readable():
    assert CareerProfile.model_validate({"roles": [], "stories": []}).facts == []
    profile = apply_fact_update(CareerProfile(), update())
    assert profile_from_markdown(profile_to_markdown(profile)) == profile


def test_fact_correction_preserves_identity_and_input():
    profile, _, _ = case()
    fact = profile.facts[0]
    revised = apply_fact_update(profile, FactUpdate(existing_fact_uuid=str(fact.fact_uuid),
        category=None, name=None, statement="I can work onsite in Kirkland."))
    assert revised.facts[0].fact_uuid == fact.fact_uuid
    assert revised.facts[0].statement != fact.statement
    assert profile_revision(revised) != profile_revision(profile)
    assert apply_fact_update(profile, update()) == profile


@pytest.mark.parametrize("changes", [
    {"existing_fact_uuid": str(uuid4())},
    {"statement": " "},
    {"statement": "I now require onsite work."},
])
def test_fact_updates_reject_unknown_blank_or_implicit_replacement(changes):
    profile, _, _ = case()
    values = update().model_dump()
    values.update(changes)
    with pytest.raises(ValueError):
        apply_fact_update(profile, FactUpdate(**values))


def test_duplicate_fact_ids_rejected():
    fact = ProfileFact(category="skill", name="Python", statement="Used Python for two years.")
    with pytest.raises(ValidationError):
        CareerProfile(facts=[fact, fact])


@pytest.mark.parametrize("classification", ["blocking", "compatible"])
def test_conclusions_require_explicit_evidence(classification):
    with pytest.raises(ValidationError):
        ConstraintAssessment(requirement_uuid=uuid4(), classification=classification,
                             explanation="Unsupported conclusion.")


def test_blocker_does_not_add_or_remove_qualification_credit():
    profile, requirements, match = case()
    score = score_profile_match(profile, requirements, match)
    assert score.percentage is None
    assert score.possible_weighted_credit == 0
    assert score.scored_qualification_count == 0
    assert score.constraint_uuids == [requirements.requirements[0].requirement_uuid]


@pytest.mark.parametrize("problem", ["excerpt", "field", "uuid", "coverage", "duplicate"])
def test_constraint_validation_rejects_fabrication_and_wrong_coverage(problem):
    profile, requirements, match = case()
    if problem == "excerpt":
        match.constraints[0].evidence[0].excerpt = "I can relocate."
    elif problem == "field":
        match.constraints[0].evidence[0].field_name = "fact_uuid"
    elif problem == "uuid":
        match.constraints[0].evidence[0].record_uuid = uuid4()
    elif problem == "coverage":
        match.constraints = []
    else:
        match.constraints.append(match.constraints[0])
    with pytest.raises(ValueError):
        validate_profile_match(profile, requirements, match)


def test_approved_preference_change_invalidates_saved_constraint_report(tmp_path):
    profile, requirements, match = case()
    database = tmp_path / "captures.sqlite"
    save_profile_match(database, profile, requirements, match)
    assert load_profile_match(database, profile, requirements) == match
    changed = apply_fact_update(profile, FactUpdate(existing_fact_uuid=str(profile.facts[0].fact_uuid),
        category=None, name=None, statement="I accept onsite work."))
    assert load_profile_match(database, changed, requirements) is None


def test_constraint_only_model_call_and_missing_evidence_are_explicit():
    profile, requirements, match = case()
    class Model:
        def with_structured_output(self, *args, **kwargs):
            return self
        def invoke(self, messages):
            self.context = messages[-1].content
            return MatchResponse(assessments=[], constraints=[ConstraintResponse(
                requirement_uuid=str(requirements.requirements[0].requirement_uuid),
                classification="blocking", explanation=match.constraints[0].explanation,
                evidence=[EvidenceResponse.model_validate(match.constraints[0].evidence[0].model_dump(mode="json"))])])
    model = Model()
    result = create_profile_match_assessor(model)(profile, requirements)
    assert result.constraints[0].classification == "blocking"
    assert "allowed_fact_evidence_fields" in model.context
    assert "practical constraint" in model.context.lower() or '"constraints"' in model.context


@pytest.mark.parametrize("category", ["preference", "skill", "project"])
def test_intake_fact_only_turn_preserves_story_and_approved_profile(category):
    from test_interview_agent import FakeModel, make_turn, make_saved_profile
    from job_application_assistant.interview_agent import create_interview_step
    from job_application_assistant.interview_state import new_interview_state
    profile = make_saved_profile()
    approved = profile_to_markdown(profile)
    state = new_interview_state(approved)
    state["active_story_uuid"] = str(profile.stories[0].story_uuid)
    proposal = FactUpdate(existing_fact_uuid=None, category=category,
                          name="Explicit user fact", statement="User-supplied detail.")
    result = create_interview_step(FakeModel(make_turn(fact_update=proposal)))(state)
    draft = CareerProfile.model_validate(result["draft_profile"])
    assert draft.roles == profile.roles
    assert draft.stories == profile.stories
    assert len(draft.facts) == 1
    assert profile_from_markdown(approved).facts == []
    assert state["current_markdown"] == approved


def test_api_persists_constraint_report_and_reuses_without_model(tmp_path):
    from fastapi.testclient import TestClient
    from job_application_assistant.capture_api import create_app
    from job_application_assistant.job_capture import JobCapture
    from job_application_assistant.job_capture_storage import save_capture
    from job_application_assistant.job_requirements_storage import save_requirements
    from job_application_assistant.job_requirements_validation import jd_text_revision
    profile, requirements, match = case()
    capture = JobCapture(capture_uuid=requirements.capture_uuid,
        source_url="https://example.com/jobs/engineer", captured_at="2026-11-19T12:00:00-08:00",
        capture_method="paste", jd_text="Must work onsite in Kirkland.")
    requirements.jd_text_sha256 = jd_text_revision(capture.jd_text)
    match.requirements_sha256 = requirements_revision(requirements)
    database = tmp_path / "capture.sqlite"
    path = tmp_path / "career_profile.md"
    path.write_text(profile_to_markdown(profile))
    save_capture(database, capture)
    save_requirements(database, requirements)
    calls = []
    def assessor(saved_profile, source):
        calls.append(1)
        return match
    app = create_app(database_path=database, api_token="test-token", profile_path=path,
                     profile_assessor=assessor)
    headers = {"X-Capture-Token": "test-token"}
    endpoint = f"/captures/{capture.capture_uuid}/profile-match"
    with TestClient(app) as client:
        assert client.post(endpoint).status_code == 401
        response = client.post(endpoint, headers=headers)
        assert response.status_code == 200
        assert response.json()["match"]["constraints"][0]["classification"] == "blocking"
        assert response.json()["score"]["percentage"] is None
        assert client.get(endpoint, headers=headers).json() == response.json()
        assert client.post(endpoint, headers=headers).json() == response.json()
    assert calls == [1]
    assert path.read_text() == profile_to_markdown(profile)


def test_skill_fact_can_support_qualification_without_constraint_credit():
    from job_application_assistant.profile_match import QualificationAssessment
    profile, requirements, match = case()
    skill = ProfileFact(category="skill", name="Python", statement="I have used Python for five years.")
    profile.facts.append(skill)
    qualification = JobRequirement(kind="qualification", importance="required",
        description="Five years of Python experience.", source_excerpt="Five years of Python experience.")
    requirements.requirements.append(qualification)
    match.profile_sha256 = profile_revision(profile)
    match.requirements_sha256 = requirements_revision(requirements)
    match.assessments = [QualificationAssessment(requirement_uuid=qualification.requirement_uuid,
        classification="strong_match", explanation="Five years are explicitly documented.",
        evidence=[ProfileEvidence(record_type="fact", record_uuid=skill.fact_uuid,
            field_name="statement", excerpt=skill.statement)])]
    score = score_profile_match(profile, requirements, match)
    assert score.percentage == 100.0
    assert score.possible_weighted_credit == 2
    assert match.constraints[0].classification == "blocking"
