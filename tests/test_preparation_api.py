"""Test browser research and interview preparation without network or AI."""

import json
import socket
import sqlite3
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi import FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from openai import OpenAIError

from job_application_assistant.interview_guide import (
    InterviewGuide, PracticeQuestion, ResearchNote,
)
from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_capture_storage import save_capture
from job_application_assistant.job_requirements import JobRequirement, JobRequirements
from job_application_assistant.job_requirements_storage import save_requirements
from job_application_assistant.job_requirements_validation import jd_text_revision
from job_application_assistant.models import CareerProfile, EducationRecord
from job_application_assistant.preparation_api import create_preparation_router, public_source
from job_application_assistant.profile_markdown import profile_to_markdown


HEADERS = {"X-Capture-Token": "preparation-test"}


@pytest.fixture
def preparation_api(tmp_path):
    database = tmp_path / "jobs.sqlite"
    profile_path = tmp_path / "career_profile.md"
    profile = CareerProfile(education=[EducationRecord(
        qualification="Bachelor of Science", status="completed",
        completion_date="2011",
    )])
    profile_path.write_text(profile_to_markdown(profile), encoding="utf-8")
    capture = JobCapture(
        source_url="https://example.com/job", capture_method="paste",
        captured_at="2026-11-19T12:00:00-08:00",
        jd_text="People leadership experience required.",
    )
    save_capture(database, capture)
    requirements = JobRequirements(
        capture_uuid=capture.capture_uuid,
        jd_text_sha256=jd_text_revision(capture.jd_text),
        company_name="Example Company", job_title="Engineering Manager",
        requirements=[JobRequirement(
            description=capture.jd_text, kind="qualification",
            importance="required", source_excerpt=capture.jd_text,
        )],
    )
    save_requirements(database, requirements)
    calls = {"fetch": [], "generate": []}
    behavior = {}

    def fetcher(url, hosts):
        calls["fetch"].append(url)
        text = "We build tools for software developers."
        return {
            "source_uuid": str(uuid4()), "url": url, "title": "About",
            "retrieved_at": "2026-11-19T20:00:00+00:00",
            "publication_date": None, "publication_date_basis": "not_available",
            "text": text, "text_sha256": sha256(text.encode()).hexdigest(),
        }

    def generator(profile, source, bundle, guidance):
        calls["generate"].append(guidance)
        if behavior.get("error"):
            raise OpenAIError("Provider unavailable")
        citation = bundle["sources"][0]
        return InterviewGuide(
            company_notes=[ResearchNote(
                statement="The company makes developer tools.",
                source_uuid=citation["source_uuid"], excerpt=citation["text"],
            )],
            documented_hiring_information=[],
            practice_questions=[PracticeQuestion(
                requirement_uuid=str(source.requirements[0].requirement_uuid),
                question=f"Describe your leadership example, topic {index}.",
                answer_draft=None,
                clarification="What was your personal contribution?",
                evidence=[],
            ) for index in range(5)],
        )

    def require_token(x_capture_token: str | None = Header(default=None)):
        if x_capture_token != "preparation-test":
            raise HTTPException(401, "Invalid token.")

    app = FastAPI()
    root = tmp_path / "preparation"
    app.include_router(create_preparation_router(
        database, profile_path, require_token,
        preparation_root=root, fetcher=fetcher, guide_generator=generator,
    ))
    with TestClient(app) as client:
        yield client, capture, calls, root, profile, profile_path, requirements, database, behavior


def capture_sources(client, capture, request_id=None):
    return client.post(f"/captures/{capture.capture_uuid}/research", headers=HEADERS, json={
        "request_uuid": str(request_id or uuid4()),
        "official_sources_confirmed": True,
        "urls": ["https://example.com/about"],
    })


def guide_body(research, request_id=None, guidance=""):
    return {
        "request_uuid": str(request_id or uuid4()),
        "research_uuid": research["research_uuid"],
        "research_sha256": research["research_sha256"],
        "sources_reviewed": True, "recruiter_guidance": guidance,
    }


def generate(client, capture, research, request_id=None, guidance=""):
    return client.post(
        f"/captures/{capture.capture_uuid}/interview-guides", headers=HEADERS,
        json=guide_body(research, request_id, guidance),
    )


def test_capture_generate_and_reopen_without_new_calls(preparation_api):
    client, capture, calls, *_ = preparation_api
    path = f"/captures/{capture.capture_uuid}"
    assert client.get(path + "/research/latest", headers=HEADERS).json() is None
    assert client.get(path + "/interview-guides/latest", headers=HEADERS).json() is None
    source_response = capture_sources(client, capture)
    assert source_response.status_code == 200
    research = source_response.json()
    guidance = "The recruiter said there is one remote interview."
    created = generate(client, capture, research, guidance=guidance)
    assert created.status_code == 200
    value = created.json()
    assert len(value["guide"]["practice_questions"]) == 5
    assert value["guide"]["documented_hiring_information"] == []
    assert guidance in value["markdown"]
    assert "Takes precedence" in value["markdown"]
    assert value["recruiter_guidance"] == guidance
    assert client.get(path + "/research/latest", headers=HEADERS).json() == research
    assert client.get(path + "/interview-guides/latest", headers=HEADERS).json() == value
    assert calls == {"fetch": ["https://example.com/about"], "generate": [guidance]}


def test_request_retries_do_not_refetch_or_regenerate(preparation_api):
    client, capture, calls, *_ = preparation_api
    request_id = uuid4()
    first = capture_sources(client, capture, request_id)
    second = capture_sources(client, capture, request_id)
    assert first.json() == second.json()
    guide_id = uuid4()
    first = generate(client, capture, first.json(), guide_id)
    research = second.json()
    second = generate(client, capture, research, guide_id)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(calls["fetch"]) == len(calls["generate"]) == 1


@pytest.mark.parametrize("kind", ["official_confirmation", "source_review", "source_hash"])
def test_explicit_review_and_source_version_are_required(preparation_api, kind):
    client, capture, calls, *_ = preparation_api
    if kind == "official_confirmation":
        response = client.post(f"/captures/{capture.capture_uuid}/research", headers=HEADERS, json={
            "request_uuid": str(uuid4()), "official_sources_confirmed": False,
            "urls": ["https://example.com/about"],
        })
        assert response.status_code == 422
        assert calls["fetch"] == []
    else:
        research = capture_sources(client, capture).json()
        body = guide_body(research)
        if kind == "source_review":
            body["sources_reviewed"] = False
        else:
            body["research_sha256"] = "0" * 64
        response = client.post(f"/captures/{capture.capture_uuid}/interview-guides", headers=HEADERS, json=body)
        assert response.status_code == (422 if kind == "source_review" else 409)
    assert calls["generate"] == []


@pytest.mark.parametrize("change", ["profile", "job", "source_file", "new_sources"])
def test_changed_inputs_flag_saved_guide_for_refresh(preparation_api, change):
    client, capture, _, root, profile, profile_path, requirements, database, _ = preparation_api
    research = capture_sources(client, capture).json()
    assert generate(client, capture, research).status_code == 200
    if change == "profile":
        profile.education[0].completion_date = "2012"
        profile_path.write_text(profile_to_markdown(profile), encoding="utf-8")
    elif change == "job":
        requirements.job_title = "New title"
        with sqlite3.connect(database) as connection:
            connection.execute("UPDATE job_requirements SET payload = ?", (requirements.model_dump_json(),))
    elif change == "source_file":
        path = root / str(capture.capture_uuid) / "research" / research["research_uuid"] / "sources.json"
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        assert capture_sources(client, capture).status_code == 200
    response = client.get(f"/captures/{capture.capture_uuid}/interview-guides/latest", headers=HEADERS)
    assert response.status_code == 409
    assert "needs refresh" in response.json()["detail"]


@pytest.mark.parametrize("endpoint", ["capture", "sources", "generate", "guide"])
def test_all_preparation_routes_require_authentication(preparation_api, endpoint):
    client, capture, calls, root, *_ = preparation_api
    path = f"/captures/{capture.capture_uuid}"
    if endpoint == "capture":
        response = client.post(path + "/research", json={
            "request_uuid": str(uuid4()), "official_sources_confirmed": True,
            "urls": ["https://example.com/about"],
        })
    elif endpoint == "generate":
        response = client.post(path + "/interview-guides", json={
            "request_uuid": str(uuid4()), "research_uuid": str(uuid4()),
            "research_sha256": "a" * 64, "sources_reviewed": True,
        })
    else:
        response = client.get(path + ("/research/latest" if endpoint == "sources" else "/interview-guides/latest"))
    assert response.status_code == 401
    assert calls == {"fetch": [], "generate": []}
    assert not root.exists()


def test_research_from_another_job_is_rejected(preparation_api):
    client, capture, calls, *_ = preparation_api
    research = capture_sources(client, capture).json()
    response = client.post(f"/captures/{uuid4()}/interview-guides", headers=HEADERS, json=guide_body(research))
    assert response.status_code == 404
    assert calls["generate"] == []


def test_model_failure_does_not_publish_partial_guide(preparation_api):
    client, capture, calls, _, _, _, _, _, behavior = preparation_api
    research = capture_sources(client, capture).json()
    behavior["error"] = True
    request_id = uuid4()
    assert generate(client, capture, research, request_id).status_code == 502
    assert generate(client, capture, research, request_id).status_code == 409
    response = client.get(f"/captures/{capture.capture_uuid}/interview-guides/latest", headers=HEADERS)
    assert response.status_code == 200
    assert response.json() is None
    assert len(calls["generate"]) == 1


def test_private_dns_destination_is_rejected_before_fetch(monkeypatch):
    import job_application_assistant.preparation_api as module
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **kw: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
    ])
    monkeypatch.setattr(module, "fetch_source", lambda *a: pytest.fail("Must not fetch private address"))
    with pytest.raises(ValueError, match="public HTTPS"):
        public_source("https://example.com/", {"example.com"})
