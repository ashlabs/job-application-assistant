"""Corrected requirements make dependent approvals and guides outdated."""

from test_resume_api import resume_api, generate as generate_resume, HEADERS as RESUME_HEADERS
from test_preparation_api import preparation_api, capture_sources, generate as generate_guide, HEADERS as PREP_HEADERS
from job_application_assistant.requirements_review import review_snapshot, save_requirements_review
from job_application_assistant.job_requirements import JobRequirements


def change_importance(database, capture):
    snapshot = review_snapshot(database, capture.capture_uuid)
    requirements = JobRequirements.model_validate(snapshot["requirements"])
    requirements.requirements[0].importance = "preferred"
    save_requirements_review(database, capture.capture_uuid, snapshot["revision"], requirements)


def test_corrected_requirements_block_old_resume_approval_and_export(resume_api):
    client, capture, calls, _, _, profile_path = resume_api
    draft = generate_resume(client, capture).json()
    endpoint = f"/captures/{capture.capture_uuid}/resumes/{draft['resume_uuid']}"
    body = {"review_token": draft["review_token"], "confirmed": True}
    assert client.post(endpoint + "/approve", headers=RESUME_HEADERS, json=body).status_code == 200
    change_importance(profile_path.parent / "jobs.sqlite", capture)
    assert client.get(f"/captures/{capture.capture_uuid}/resumes/latest", headers=RESUME_HEADERS).status_code == 409
    assert client.post(endpoint + "/approve", headers=RESUME_HEADERS, json=body).status_code == 409
    assert client.post(endpoint + "/export", headers=RESUME_HEADERS, json=body).status_code == 409
    assert calls == [True]


def test_corrected_requirements_invalidate_guide_without_fetching_or_generating(preparation_api):
    client, capture, calls, _, _, _, _, database, _ = preparation_api
    research = capture_sources(client, capture).json()
    assert generate_guide(client, capture, research).status_code == 200
    change_importance(database, capture)
    response = client.get(f"/captures/{capture.capture_uuid}/interview-guides/latest", headers=PREP_HEADERS)
    assert response.status_code == 409
    assert "changed" in response.json()["detail"].lower() or "outdated" in response.json()["detail"].lower()
    assert calls == {"fetch": ["https://example.com/about"], "generate": [""]}
