"""Exercise the authenticated browser resume workflow without AI calls."""

import base64
from io import BytesIO
from uuid import uuid4

import pytest
from docx import Document
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from pypdf import PdfReader

from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_capture_storage import save_capture
from job_application_assistant.job_requirements import JobRequirement, JobRequirements
from job_application_assistant.job_requirements_storage import save_requirements
from job_application_assistant.job_requirements_validation import jd_text_revision
from job_application_assistant.models import CareerProfile, EducationRecord
from job_application_assistant.profile_markdown import profile_to_markdown
from job_application_assistant.resume_api import create_resume_router
from job_application_assistant.resume_draft import ResumeSelection


HEADERS = {"X-Capture-Token": "test-token"}


@pytest.fixture
def resume_api(tmp_path):
    database = tmp_path / "jobs.sqlite"
    profile_path = tmp_path / "career_profile.md"
    record = EducationRecord(
        qualification="Bachelor of Science", status="completed",
        completion_date="2011",
    )
    profile = CareerProfile(education=[record])
    profile_path.write_text(profile_to_markdown(profile), encoding="utf-8")
    capture = JobCapture(
        source_url="https://example.com/job", capture_method="paste",
        captured_at="2026-11-19T12:00:00-08:00",
        jd_text="Bachelor's degree required.",
    )
    save_capture(database, capture)
    save_requirements(database, JobRequirements(
        capture_uuid=capture.capture_uuid,
        jd_text_sha256=jd_text_revision(capture.jd_text),
        requirements=[JobRequirement(
            description=capture.jd_text, kind="qualification",
            importance="required", source_excerpt=capture.jd_text,
        )],
    ))
    calls = []

    def selector(profile, requirements):
        calls.append(True)
        return ResumeSelection(
            role_ids=[], story_ids=[],
            education_ids=[str(record.education_uuid)],
        )

    def require_token(x_capture_token: str | None = Header(default=None)):
        if x_capture_token != "test-token":
            raise HTTPException(401, "Invalid token.")

    app = FastAPI()
    root = tmp_path / "resumes"
    app.include_router(create_resume_router(
        database, profile_path, require_token,
        resume_root=root, selector=selector,
    ))
    with TestClient(app) as client:
        yield client, capture, calls, root, profile, profile_path


def generate(client, capture, request_id=None):
    return client.post(
        f"/captures/{capture.capture_uuid}/resumes", headers=HEADERS,
        json={"request_uuid": str(request_id or uuid4()),
              "name": "Example Candidate"},
    )


def test_browser_resume_approval_export_and_reload(resume_api):
    client, capture, calls, _, _, _ = resume_api
    created = generate(client, capture)
    assert created.status_code == 200
    draft = created.json()
    path = f"/captures/{capture.capture_uuid}/resumes"
    target = f"{path}/{draft['resume_uuid']}"
    body = {"confirmed": True, "review_token": draft["review_token"]}
    assert not draft["approved"]
    assert client.post(target + "/export", headers=HEADERS, json=body).status_code == 409
    approved = client.post(target + "/approve", headers=HEADERS, json=body)
    assert approved.status_code == 200
    assert approved.json()["approved"]
    # Approval is idempotent if the exact draft is unchanged.
    assert client.post(target + "/approve", headers=HEADERS, json=body).status_code == 200
    exported = client.post(target + "/export", headers=HEADERS, json=body)
    assert exported.status_code == 200
    files = exported.json()["files"]
    doc = Document(BytesIO(base64.b64decode(files["resume.docx"])))
    pdf = PdfReader(BytesIO(base64.b64decode(files["resume.pdf"])))
    assert "Example Candidate" in doc.paragraphs[0].text
    assert "Completed" in pdf.pages[0].extract_text()
    loaded = client.get(path + "/latest", headers=HEADERS)
    assert loaded.json() == approved.json()
    assert len(calls) == 1


def test_generation_retry_reuses_request_id_without_ai(resume_api):
    client, capture, calls, _, _, _ = resume_api
    request_id = uuid4()
    first = generate(client, capture, request_id)
    second = generate(client, capture, request_id)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(calls) == 1


@pytest.mark.parametrize("action", ["approve", "export"])
def test_changed_review_token_is_rejected(resume_api, action):
    client, capture, _, _, _, _ = resume_api
    draft = generate(client, capture).json()
    response = client.post(
        f"/captures/{capture.capture_uuid}/resumes/{draft['resume_uuid']}/{action}",
        headers=HEADERS,
        json={"confirmed": True, "review_token": "0" * 64},
    )
    assert response.status_code == 409


def test_profile_change_blocks_existing_draft(resume_api):
    client, capture, _, _, profile, profile_path = resume_api
    draft = generate(client, capture).json()
    target = f"/captures/{capture.capture_uuid}/resumes/{draft['resume_uuid']}"
    body = {"confirmed": True, "review_token": draft["review_token"]}
    assert client.post(target + "/approve", headers=HEADERS, json=body).status_code == 200
    profile.education[0].completion_date = "2012"
    profile_path.write_text(profile_to_markdown(profile), encoding="utf-8")
    assert client.post(target + "/export", headers=HEADERS, json=body).status_code == 409
    assert client.get(f"/captures/{capture.capture_uuid}/resumes/latest", headers=HEADERS).status_code == 409


def test_resume_cannot_be_approved_under_another_job(resume_api):
    client, capture, _, _, _, _ = resume_api
    draft = generate(client, capture).json()
    response = client.post(
        f"/captures/{uuid4()}/resumes/{draft['resume_uuid']}/approve",
        headers=HEADERS,
        json={"confirmed": True, "review_token": draft["review_token"]},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("endpoint", ["generate", "latest", "approve", "export"])
def test_all_resume_routes_require_authentication(resume_api, endpoint):
    client, capture, calls, root, _, _ = resume_api
    path = f"/captures/{capture.capture_uuid}/resumes"
    if endpoint == "generate":
        response = client.post(path, json={
            "request_uuid": str(uuid4()), "name": "Example Candidate",
        })
    elif endpoint == "latest":
        response = client.get(path + "/latest")
    else:
        response = client.post(path + f"/{uuid4()}/{endpoint}", json={
            "confirmed": True, "review_token": "0" * 64,
        })
    assert response.status_code == 401
    assert calls == []
    assert not root.exists()


def test_latest_before_generation_is_empty(resume_api):
    client, capture, calls, _, _, _ = resume_api
    response = client.get(
        f"/captures/{capture.capture_uuid}/resumes/latest", headers=HEADERS
    )
    assert response.status_code == 200
    assert response.json() is None
    assert calls == []


@pytest.mark.parametrize("action", ["approve", "export"])
def test_resume_actions_require_explicit_confirmation(resume_api, action):
    client, capture, _, _, _, _ = resume_api
    draft = generate(client, capture).json()
    response = client.post(
        f"/captures/{capture.capture_uuid}/resumes/{draft['resume_uuid']}/{action}",
        headers=HEADERS,
        json={"confirmed": False, "review_token": draft["review_token"]},
    )
    assert response.status_code == 422
