"""Explicit corrections preserve sources and reject stale or unsupported edits."""

import sqlite3
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pytest

from test_job_requirements_api import extraction_api, HEADERS
from job_application_assistant.job_capture_storage import load_capture
from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.job_requirements_storage import load_requirements
from job_application_assistant.requirements_review import (
    RequirementsReviewConflict, review_snapshot, save_requirements_review,
)


def start(api):
    client, database, capture, extractor = api
    path = f"/captures/{capture.capture_uuid}/requirements"
    assert client.post(path, headers=HEADERS).status_code == 200
    response = client.get(path + "/review", headers=HEADERS)
    assert response.status_code == 200
    return path + "/review", response.json()


def correction(snapshot):
    return {"expected_revision": snapshot["revision"],
            "requirements": deepcopy(snapshot["requirements"]), "confirmed": True}


def test_review_save_reopen_no_ai_source_unchanged_and_history(extraction_api):
    client, database, capture, extractor = extraction_api
    path, snapshot = start(extraction_api)
    body = correction(snapshot)
    original_id = body["requirements"]["requirements"][0]["requirement_uuid"]
    body["requirements"]["requirements"][0]["importance"] = "preferred"
    saved = client.put(path, headers=HEADERS, json=body)
    assert saved.status_code == 200
    assert saved.json()["revision"] != snapshot["revision"]
    assert saved.json()["requirements"]["requirements"][0]["requirement_uuid"] == original_id
    assert client.get(path, headers=HEADERS).json() == saved.json()
    assert client.put(path, headers=HEADERS, json=body).json() == saved.json()
    assert load_capture(database, capture.capture_uuid) == capture
    assert len(extractor.calls) == 1
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT previous_payload, payload FROM requirement_review_history").fetchall()
    assert len(rows) == 1
    assert '"required"' in rows[0][0]
    assert '"preferred"' in rows[0][1]


@pytest.mark.parametrize("problem", ["confirmation", "source", "hash", "capture", "uuid", "duplicate", "empty", "importance"])
def test_invalid_correction_leaves_storage_unchanged(extraction_api, problem):
    client, database, capture, extractor = extraction_api
    path, snapshot = start(extraction_api)
    body = correction(snapshot)
    item = body["requirements"]["requirements"][0]
    if problem == "confirmation": body["confirmed"] = False
    elif problem == "source": item["source_excerpt"] = "Not in the original JD."
    elif problem == "hash": body["requirements"]["jd_text_sha256"] = "b" * 64
    elif problem == "capture": body["requirements"]["capture_uuid"] = str(uuid4())
    elif problem == "uuid": body["requirements"]["requirements"].append(dict(item))
    elif problem == "duplicate":
        duplicate = dict(item, requirement_uuid=str(uuid4()), description=" EXPERIENCE conducting CUSTOMER interviews. ")
        body["requirements"]["requirements"].append(duplicate)
    elif problem == "empty": item["description"] = " "
    else: item["importance"] = "critical"
    assert client.put(path, headers=HEADERS, json=body).status_code == 422
    current = load_requirements(database, capture.capture_uuid)
    assert current.requirements[0].importance == "required"
    assert len(current.requirements) == 1
    assert len(extractor.calls) == 1


def test_stale_editor_cannot_overwrite_new_review(extraction_api):
    client, _, _, _ = extraction_api
    path, snapshot = start(extraction_api)
    first = correction(snapshot)
    first["requirements"]["requirements"][0]["importance"] = "preferred"
    assert client.put(path, headers=HEADERS, json=first).status_code == 200
    first["requirements"]["requirements"][0]["importance"] = "unspecified"
    response = client.put(path, headers=HEADERS, json=first)
    assert response.status_code == 409
    assert "another tab" in response.json()["detail"]


def test_add_remove_and_reclassify_preserves_remaining_ids(extraction_api):
    client, _, _, _ = extraction_api
    path, snapshot = start(extraction_api)
    body = correction(snapshot)
    original = body["requirements"]["requirements"][0]
    new = dict(original, requirement_uuid=str(uuid4()), description="Customer interviews.", kind="constraint")
    body["requirements"]["requirements"] = [new]
    response = client.put(path, headers=HEADERS, json=body)
    assert response.status_code == 200
    assert response.json()["requirements"]["requirements"] == [new]


def test_review_requires_auth_and_extraction(extraction_api):
    client, _, capture, extractor = extraction_api
    path = f"/captures/{capture.capture_uuid}/requirements/review"
    assert client.get(path).status_code == 401
    assert client.get(path, headers=HEADERS).status_code == 409
    assert extractor.calls == []
    assert client.get(f"/captures/{uuid4()}/requirements/review", headers=HEADERS).status_code == 404


def test_concurrent_saves_accept_only_one_revision(extraction_api):
    _, database, capture, _ = extraction_api
    _, snapshot = start(extraction_api)
    def save(importance):
        requirements = JobRequirements.model_validate(snapshot["requirements"])
        requirements.requirements[0].importance = importance
        try:
            save_requirements_review(database, capture.capture_uuid, snapshot["revision"], requirements)
            return "saved"
        except RequirementsReviewConflict:
            return "conflict"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, ["preferred", "unspecified"]))
    assert sorted(results) == ["conflict", "saved"]


def test_duplicate_extraction_can_be_opened_and_fixed(extraction_api):
    client, database, capture, _ = extraction_api
    path, snapshot = start(extraction_api)
    requirements = snapshot["requirements"]
    requirements["requirements"].append(dict(requirements["requirements"][0], requirement_uuid=str(uuid4())))
    import json
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE job_requirements SET payload=?", (json.dumps(requirements),))
    response = client.get(path, headers=HEADERS)
    assert len(response.json()["duplicate_groups"]) == 1
    body = correction(response.json())
    body["requirements"]["requirements"].pop()
    assert client.put(path, headers=HEADERS, json=body).status_code == 200


def test_correction_invalidates_existing_match(extraction_api, tmp_path):
    from job_application_assistant.models import CareerProfile
    from job_application_assistant.profile_match import ProfileMatch, QualificationAssessment
    from job_application_assistant.profile_match_storage import save_profile_match, load_profile_match
    from job_application_assistant.profile_match_validation import profile_revision
    client, database, capture, _ = extraction_api
    path, snapshot = start(extraction_api)
    requirements = JobRequirements.model_validate(snapshot["requirements"])
    profile = CareerProfile()
    match = ProfileMatch(capture_uuid=capture.capture_uuid, profile_sha256=profile_revision(profile),
        requirements_sha256=snapshot["revision"], assessments=[QualificationAssessment(
            requirement_uuid=requirements.requirements[0].requirement_uuid,
            classification="evidence_missing", explanation="No profile evidence.")])
    save_profile_match(database, profile, requirements, match)
    body = correction(snapshot)
    body["requirements"]["requirements"][0]["importance"] = "preferred"
    assert client.put(path, headers=HEADERS, json=body).status_code == 200
    current = load_requirements(database, capture.capture_uuid)
    assert load_profile_match(database, profile, current) is None


def test_review_limit_and_put_authentication(extraction_api):
    client, _, _, _ = extraction_api
    path, snapshot = start(extraction_api)
    body = correction(snapshot)
    assert client.put(path, json=body).status_code == 401
    original = body["requirements"]["requirements"][0]
    body["requirements"]["requirements"] = [
        dict(original, requirement_uuid=str(uuid4()), description=f"Reviewed item {index}")
        for index in range(201)
    ]
    assert client.put(path, headers=HEADERS, json=body).status_code == 422
    assert client.get(path, headers=HEADERS).json() == snapshot
