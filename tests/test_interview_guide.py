"""Reject fabricated guide references and unsupported answer drafts."""

from hashlib import sha256
from uuid import uuid4

import pytest

from job_application_assistant.interview_guide import (
    InterviewGuide,
    PracticeQuestion,
    ResearchNote,
    render_guide,
    validate_guide,
)
from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements,
)
from job_application_assistant.models import CareerProfile


@pytest.fixture
def guide_case():
    requirement = JobRequirement(
        description="People leadership experience.",
        kind="qualification",
        importance="required",
        source_excerpt="People leadership experience.",
    )
    requirements = JobRequirements(
        capture_uuid=uuid4(),
        jd_text_sha256="a" * 64,
        company_name="Example Company",
        requirements=[requirement],
    )
    source_id = str(uuid4())
    text = "We build tools for software developers."
    bundle = {
        "company": "Example Company",
        "allowed_hosts": ["example.com"],
        "sources": [
            {
                "source_uuid": source_id,
                "url": "https://example.com/about",
                "title": "About",
                "text": text,
                "text_sha256": sha256(text.encode()).hexdigest(),
                "retrieved_at": "2026-11-19T20:00:00+00:00",
                "publication_date": None,
            }
        ],
    }
    guide = InterviewGuide(
        company_notes=[
            ResearchNote(
                statement="The company builds developer tools.",
                source_uuid=source_id,
                excerpt=text,
            )
        ],
        documented_hiring_information=[],
        practice_questions=[
            PracticeQuestion(
                requirement_uuid=str(requirement.requirement_uuid),
                question=f"Describe a leadership example, topic {index}.",
                answer_draft=None,
                clarification="What did you personally do?",
                evidence=[],
            )
            for index in range(5)
        ],
    )
    return guide, CareerProfile(), requirements, bundle


def test_valid_guide_keeps_unknown_hiring_information_explicit(guide_case):
    guide, profile, requirements, bundle = guide_case
    validate_guide(guide, profile, requirements, bundle)
    rendered = render_guide(guide, bundle)
    assert "Not established by the captured sources." in rendered
    assert "Generated practice questions" in rendered
    assert "https://example.com/about" in rendered


@pytest.mark.parametrize(
    "problem",
    [
        "unknown_source",
        "invented_excerpt",
        "changed_source",
        "unknown_requirement",
        "unsupported_answer",
        "duplicate_question",
        "missing_question",
        "missing_clarification",
    ],
)
def test_invalid_guide_is_rejected(guide_case, problem):
    guide, profile, requirements, bundle = guide_case
    if problem == "unknown_source":
        guide.company_notes[0].source_uuid = str(uuid4())
    elif problem == "invented_excerpt":
        guide.company_notes[0].excerpt = "There are four interviews."
    elif problem == "changed_source":
        bundle["sources"][0]["text"] = "Changed source text."
    elif problem == "unknown_requirement":
        guide.practice_questions[0].requirement_uuid = str(uuid4())
    elif problem == "unsupported_answer":
        guide.practice_questions[0].answer_draft = "I led 50 engineers."
    elif problem == "duplicate_question":
        guide.practice_questions[1].question = (
            guide.practice_questions[0].question
        )
    elif problem == "missing_question":
        guide.practice_questions.pop()
    else:
        guide.practice_questions[0].clarification = None

    with pytest.raises(ValueError):
        validate_guide(guide, profile, requirements, bundle)

def test_recruiter_guidance_is_separate_from_company_sources(guide_case):
    from job_application_assistant.interview_guide import generate_guide
    import json

    guide, profile, requirements, bundle = guide_case
    guidance = "Recruiter: one remote conversation, not an onsite loop."

    class FakeModel:
        def with_structured_output(self, schema, **kwargs):
            assert schema is InterviewGuide
            return self

        def invoke(self, messages):
            context = json.loads(messages[-1].content)
            assert context["recruiter_guidance"] == guidance
            assert "takes precedence" in messages[0].content
            return guide

    result = generate_guide(FakeModel(), profile, requirements, bundle, guidance)
    rendered = render_guide(result, bundle, guidance)
    assert "Recruiter guidance — user supplied" in rendered
    assert guidance in rendered
    assert result.documented_hiring_information == []


def test_approved_project_fact_is_citable_but_invented_excerpt_is_rejected(guide_case):
    from job_application_assistant.models import ProfileFact
    from job_application_assistant.profile_match_agent import EvidenceResponse
    guide, profile, requirements, bundle = guide_case
    fact = ProfileFact(category="project", name="Reliability initiative",
                       statement="I coached engineers during a reliability initiative.")
    profile.facts = [fact]
    question = guide.practice_questions[0]
    question.answer_draft = fact.statement
    question.clarification = None
    question.evidence = [EvidenceResponse(record_type="fact", record_uuid=str(fact.fact_uuid),
        field_name="statement", excerpt=fact.statement)]
    validate_guide(guide, profile, requirements, bundle)
    question.evidence[0].excerpt = "I managed 50 engineers."
    with pytest.raises(ValueError):
        validate_guide(guide, profile, requirements, bundle)
