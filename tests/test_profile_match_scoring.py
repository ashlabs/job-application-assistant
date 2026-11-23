"""Hand-calculated checks for documented-match scoring."""

from uuid import uuid4

import pytest

from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.models import CareerProfile, ExperienceStory
from job_application_assistant.profile_match import (
    ProfileEvidence,
    ProfileMatch,
    QualificationAssessment
)
from job_application_assistant.profile_match_scoring import (
    score_profile_match
)
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision
)


def make_inputs(specifications):
    """Build structural fixtures to isolate scoring arithmetic."""
    story = ExperienceStory(
        title="Scoring evidence fixture",
        action="Interviewed customers.",
        reflection="I have no SQL experience."
    )
    profile = CareerProfile(stories=[story])
    items = []
    assessments = []

    for index, (kind, importance, classification) in enumerate(
        specifications
    ):
        requirement = JobRequirement(
            description=f"Scoring fixture requirement {index}.",
            kind=kind,
            importance=importance,
            source_excerpt=f"Source fixture {index}."
        )
        items.append(requirement)

        if kind == "constraint":
            continue

        evidence = []
        if classification != "evidence_missing":
            field = (
                "reflection"
                if classification == "confirmed_gap"
                else "action"
            )
            evidence = [
                ProfileEvidence(
                    record_type="story",
                    record_uuid=story.story_uuid,
                    field_name=field,
                    excerpt=getattr(story, field)
                )
            ]

        assessments.append(
            QualificationAssessment(
                requirement_uuid=requirement.requirement_uuid,
                classification=classification,
                explanation="Fixed classification for an arithmetic test.",
                evidence=evidence
            )
        )

    requirements = JobRequirements(
        capture_uuid=uuid4(),
        jd_text_sha256="0" * 64,
        requirements=items
    )
    match = ProfileMatch(
        capture_uuid=requirements.capture_uuid,
        requirements_sha256=requirements_revision(requirements),
        profile_sha256=profile_revision(profile),
        assessments=assessments
    )

    return profile, requirements, match


def test_required_and_preferred_weights_match_hand_calculation():
    inputs = make_inputs(
        [
            ("qualification", "required", "strong_match"),
            ("qualification", "required", "transferable_experience"),
            ("qualification", "preferred", "evidence_missing")
        ]
    )

    score = score_profile_match(*inputs)

    # Earned: 2 * 1 + 2 * 0.5 + 1 * 0 = 3.
    # Possible: 2 + 2 + 1 = 5. Percentage: 60%.
    assert score.percentage == 60.0
    assert score.earned_weighted_credit == 3.0
    assert score.possible_weighted_credit == 5
    assert score.scored_qualification_count == 3


@pytest.mark.parametrize(
    ("classification", "expected_percentage"),
    [
        ("strong_match", 100.0),
        ("transferable_experience", 50.0),
        ("evidence_missing", 0.0),
        ("confirmed_gap", 0.0)
    ]
)
def test_classification_credit(classification, expected_percentage):
    inputs = make_inputs(
        [("qualification", "required", classification)]
    )

    score = score_profile_match(*inputs)

    assert score.percentage == expected_percentage
    assert score.possible_weighted_credit == 2


def test_constraints_and_unspecified_importance_do_not_affect_score():
    profile, requirements, match = make_inputs(
        [
            ("qualification", "preferred", "strong_match"),
            ("qualification", "unspecified", "evidence_missing"),
            ("constraint", "required", None)
        ]
    )

    score = score_profile_match(profile, requirements, match)

    assert score.percentage == 100.0
    assert score.possible_weighted_credit == 1
    assert score.scored_qualification_count == 1
    assert score.unspecified_qualification_uuids == [
        requirements.requirements[1].requirement_uuid
    ]
    assert score.constraint_uuids == [
        requirements.requirements[2].requirement_uuid
    ]


def test_no_scoreable_qualifications_returns_not_available():
    inputs = make_inputs(
        [
            ("qualification", "unspecified", "evidence_missing"),
            ("constraint", "required", None)
        ]
    )

    score = score_profile_match(*inputs)

    assert score.percentage is None
    assert score.earned_weighted_credit == 0
    assert score.possible_weighted_credit == 0
    assert score.scored_qualification_count == 0


def test_stale_assessment_cannot_be_scored():
    profile, requirements, match = make_inputs(
        [("qualification", "required", "strong_match")]
    )
    profile.stories[0].action = "Reviewed customer support tickets."

    with pytest.raises(ValueError, match="profile changed"):
        score_profile_match(profile, requirements, match)

def test_per_qualification_credits_reconcile_and_preserve_jd_order():
    from job_application_assistant.scoring_rules import SCORING_RULES_VERSION
    specifications = [
        ("qualification", importance, classification)
        for importance in ("required", "preferred", "unspecified")
        for classification in (
            "strong_match", "transferable_experience", "evidence_missing", "confirmed_gap"
        )
    ] + [("constraint", "required", None)]
    profile, requirements, match = make_inputs(specifications)
    score = score_profile_match(profile, requirements, match)
    assert score.scoring_rules_version == match.scoring_rules_version == SCORING_RULES_VERSION
    assert [item.requirement_uuid for item in score.contributions] == [
        item.requirement_uuid for item in requirements.requirements if item.kind == "qualification"
    ]
    assert [item.classification_credit for item in score.contributions[:4]] == [1, .5, 0, 0]
    assert [item.earned_weighted_credit for item in score.contributions[:4]] == [2, 1, 0, 0]
    assert [item.earned_weighted_credit for item in score.contributions[4:8]] == [1, .5, 0, 0]
    assert all(item.weight is None and item.exclusion_reason == "unspecified_importance"
               and item.earned_weighted_credit == item.possible_weighted_credit == 0
               for item in score.contributions[8:])
    assert sum(item.earned_weighted_credit for item in score.contributions) == score.earned_weighted_credit == 4.5
    assert sum(item.possible_weighted_credit for item in score.contributions) == score.possible_weighted_credit == 12
    assert score.percentage == 37.5


def test_percentage_rounds_once_after_exact_half_credit_accumulation():
    inputs = make_inputs([
        ("qualification", "required", "strong_match"),
        ("qualification", "required", "transferable_experience"),
        ("qualification", "required", "evidence_missing"),
        ("qualification", "preferred", "evidence_missing"),
    ])
    score = score_profile_match(*inputs)
    assert score.earned_weighted_credit == 3
    assert score.possible_weighted_credit == 7
    assert score.percentage == 42.9


def test_an_assessment_from_another_policy_cannot_be_scored():
    profile, requirements, match = make_inputs([("qualification", "required", "strong_match")])
    match.scoring_rules_version = "documented-alignment-v0"
    with pytest.raises(ValueError, match="Scoring rules changed"):
        score_profile_match(profile, requirements, match)
