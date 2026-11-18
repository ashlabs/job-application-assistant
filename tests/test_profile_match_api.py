"""Tests for authenticated assessment of the configured saved profile."""

import sqlite3
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openai import OpenAIError

from job_application_assistant.capture_api import create_app
from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_capture_storage import save_capture
from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.job_requirements_storage import (
    save_requirements
)
from job_application_assistant.job_requirements_validation import (
    jd_text_revision
)
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_markdown import profile_to_markdown
from job_application_assistant.profile_match import (
    ProfileMatch,
    QualificationAssessment
)
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision
)


HEADERS = {"X-Capture-Token": "match-api-test-token"}


@pytest.fixture
def match_api(tmp_path):
    database = tmp_path / "captures.sqlite"
    profile_path = tmp_path / "career_profile.md"
    profile_path.write_text(
        profile_to_markdown(CareerProfile()),
        encoding="utf-8"
    )

    capture = JobCapture(
        source_url="https://example.com/jobs/product-manager",
        captured_at="2026-11-18T13:00:00-08:00",
        capture_method="paste",
        jd_text="Required: 8 years of product management experience."
    )
    save_capture(database, capture)

    requirements = JobRequirements(
        capture_uuid=capture.capture_uuid,
        jd_text_sha256=jd_text_revision(capture.jd_text),
        requirements=[
            JobRequirement(
                description="8 years of product management experience.",
                kind="qualification",
                importance="required",
                source_excerpt=capture.jd_text
            )
        ]
    )
    save_requirements(database, requirements)

    calls = []
    behavior = {}

    def assessor(profile, source):
        calls.append((profile, source))

        if "error" in behavior:
            raise behavior["error"]

        return ProfileMatch(
            capture_uuid=source.capture_uuid,
            profile_sha256=profile_revision(profile),
            requirements_sha256=requirements_revision(source),
            assessments=[
                QualificationAssessment(
                    requirement_uuid=(
                        uuid4()
                        if behavior.get("invalid")
                        else source.requirements[0].requirement_uuid
                    ),
                    classification="evidence_missing",
                    explanation="The profile does not document duration."
                )
            ]
        )

    app = create_app(
        database_path=database,
        api_token=HEADERS["X-Capture-Token"],
        profile_path=profile_path,
        profile_assessor=assessor
    )

    with TestClient(app) as client:
        yield client, database, profile_path, capture, calls, behavior


def test_assessment_returns_validated_report_and_score(match_api):
    client, _, profile_path, capture, calls, _ = match_api
    original = profile_path.read_bytes()

    response = client.post(
        f"/captures/{capture.capture_uuid}/profile-match",
        headers=HEADERS
    )

    assert response.status_code == 200
    assert response.json()["match"]["capture_uuid"] == str(
        capture.capture_uuid
    )
    assert response.json()["score"]["percentage"] == 0.0
    assert len(calls) == 1
    assert calls[0][0] == CareerProfile()
    assert profile_path.read_bytes() == original


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_assessment_requires_token(match_api, token):
    client, _, _, capture, calls, _ = match_api
    headers = {} if token is None else {"X-Capture-Token": token}

    response = client.post(
        f"/captures/{capture.capture_uuid}/profile-match",
        headers=headers
    )

    assert response.status_code == 401
    assert calls == []


def test_missing_capture_blocks_assessment(match_api):
    client, _, _, _, calls, _ = match_api

    response = client.post(
        f"/captures/{uuid4()}/profile-match",
        headers=HEADERS
    )

    assert response.status_code == 404
    assert calls == []


def test_missing_extraction_blocks_assessment(match_api):
    client, database, _, capture, calls, _ = match_api

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM job_requirements")

    response = client.post(
        f"/captures/{capture.capture_uuid}/profile-match",
        headers=HEADERS
    )

    assert response.status_code == 409
    assert calls == []


@pytest.mark.parametrize(
    ("problem", "expected_status"),
    [("missing", 409), ("invalid", 422)]
)
def test_unavailable_profile_blocks_assessment(
    match_api,
    problem,
    expected_status
):
    client, _, profile_path, capture, calls, _ = match_api

    if problem == "missing":
        profile_path.unlink()
    else:
        profile_path.write_text("Invalid profile.", encoding="utf-8")

    response = client.post(
        f"/captures/{capture.capture_uuid}/profile-match",
        headers=HEADERS
    )

    assert response.status_code == expected_status
    assert calls == []


def test_provider_failure_returns_no_report(match_api):
    client, _, _, capture, calls, behavior = match_api
    behavior["error"] = OpenAIError("Simulated provider failure")

    response = client.post(
        f"/captures/{capture.capture_uuid}/profile-match",
        headers=HEADERS
    )

    assert response.status_code == 502
    assert "match" not in response.json()
    assert len(calls) == 1


def test_invalid_assessment_returns_no_report(match_api):
    client, _, _, capture, _, behavior = match_api
    behavior["invalid"] = True

    response = client.post(
        f"/captures/{capture.capture_uuid}/profile-match",
        headers=HEADERS
    )

    assert response.status_code == 502
    assert "score" not in response.json()