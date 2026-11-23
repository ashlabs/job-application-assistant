"""Tests for the local job-capture API."""

from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from job_application_assistant.capture_api import create_app
from job_application_assistant.job_capture_storage import load_capture


TEST_TOKEN = "local-test-token"


@pytest.fixture
def api(tmp_path):
    database = tmp_path / "captures.sqlite"
    app = create_app(
        database_path=database,
        api_token=TEST_TOKEN
    )

    with TestClient(app) as client:
        yield client, database


def make_request():
    """Return a fictional, confirmed capture."""
    return {
        "confirmed": True,
        "capture": {
            "capture_uuid": str(uuid4()),
            "source_url": "https://example.com/jobs/product-manager",
            "page_title": "Product Manager",
            "captured_at": "2026-11-18T08:00:00-08:00",
            "capture_method": "selection",
            "jd_text": "Lead product discovery and prioritization."
        }
    }


def auth_headers():
    return {"X-Capture-Token": TEST_TOKEN}


def test_confirmed_capture_is_saved(api):
    client, database = api
    payload = make_request()

    response = client.post(
        "/captures",
        json=payload,
        headers=auth_headers()
    )

    assert response.status_code == 201
    assert response.json() == {
        "capture_uuid": payload["capture"]["capture_uuid"],
        "status": "created"
    }

    saved = load_capture(
        database,
        UUID(payload["capture"]["capture_uuid"])
    )
    assert saved.jd_text == payload["capture"]["jd_text"]


def test_identical_retry_returns_already_saved(api):
    client, _ = api
    payload = make_request()

    first = client.post(
        "/captures", json=payload, headers=auth_headers()
    )
    retry = client.post(
        "/captures", json=payload, headers=auth_headers()
    )

    assert first.status_code == 201
    assert retry.status_code == 200
    assert retry.json()["status"] == "already_saved"


def test_conflicting_retry_preserves_original(api):
    client, database = api
    payload = make_request()

    first = client.post(
        "/captures", json=payload, headers=auth_headers()
    )
    assert first.status_code == 201

    payload["capture"]["jd_text"] = "Different content."
    response = client.post(
        "/captures", json=payload, headers=auth_headers()
    )

    assert response.status_code == 409
    saved = load_capture(
        database,
        UUID(payload["capture"]["capture_uuid"]),
    )
    assert saved.jd_text == "Lead product discovery and prioritization."


@pytest.mark.parametrize("token", [None, "incorrect-token"])
def test_missing_or_wrong_token_rejected(api, token):
    client, database = api
    headers = {} if token is None else {"X-Capture-Token": token}

    response = client.post(
        "/captures",
        json=make_request(),
        headers=headers
    )

    assert response.status_code == 401
    assert not database.exists()


@pytest.mark.parametrize("confirmation", [False, None])
def test_unconfirmed_capture_rejected(api, confirmation):
    client, database = api
    payload = make_request()

    if confirmation is None:
        del payload["confirmed"]
    else:
        payload["confirmed"] = confirmation

    response = client.post(
        "/captures", json=payload, headers=auth_headers()
    )

    assert response.status_code == 422
    assert not database.exists()


def test_missing_capture_uuid_rejected(api):
    client, database = api
    payload = make_request()
    del payload["capture"]["capture_uuid"]

    response = client.post(
        "/captures", json=payload, headers=auth_headers()
    )

    assert response.status_code == 422
    assert not database.exists()


def test_blank_job_description_rejected(api):
    client, database = api
    payload = make_request()
    payload["capture"]["jd_text"] = "   "

    response = client.post(
        "/captures", json=payload, headers=auth_headers()
    )

    assert response.status_code == 422
    assert not database.exists()


def test_storage_failure_returns_service_unavailable(tmp_path):
    # A directory cannot be opened as a SQLite database file.
    database = tmp_path / "blocked.sqlite"
    database.mkdir()

    app = create_app(
        database_path=database,
        api_token=TEST_TOKEN
    )

    with TestClient(app) as client:
        response = client.post(
            "/captures",
            json=make_request(),
            headers=auth_headers()
        )

    assert response.status_code == 503
    assert response.json()["detail"] == (
        "Capture storage is unavailable. Retry later."
    )

def test_list_captures_returns_empty_before_first_save(api):
    client, database = api

    response = client.get("/captures", headers=auth_headers())

    assert response.status_code == 200
    assert response.json() == []
    assert not database.exists()


def test_list_and_detail_return_saved_capture(api):
    client, _ = api
    payload = make_request()

    saved = client.post(
        "/captures", json=payload, headers=auth_headers()
    )
    assert saved.status_code == 201

    listing = client.get("/captures", headers=auth_headers())
    assert listing.status_code == 200
    assert len(listing.json()) == 1

    capture_uuid = payload["capture"]["capture_uuid"]
    detail = client.get(
        f"/captures/{capture_uuid}",
        headers=auth_headers()
    )

    assert detail.status_code == 200
    assert detail.json() == listing.json()[0]
    assert detail.json()["capture_uuid"] == capture_uuid
    assert detail.json()["jd_text"] == payload["capture"]["jd_text"]
    assert detail.json()["source_url"] == payload["capture"]["source_url"]


@pytest.mark.parametrize("token", [None, "incorrect-token"])
@pytest.mark.parametrize(
    "path",
    ["/captures", f"/captures/{uuid4()}"]
)
def test_read_endpoints_require_token(api, token, path):
    client, database = api
    headers = {} if token is None else {"X-Capture-Token": token}

    response = client.get(path, headers=headers)

    assert response.status_code == 401
    assert not database.exists()


def test_missing_capture_detail_returns_not_found(api):
    client, database = api

    response = client.get(
        f"/captures/{uuid4()}",
        headers=auth_headers()
    )

    assert response.status_code == 404
    assert not database.exists()


def test_invalid_capture_identifier_rejected(api):
    client, database = api

    response = client.get(
        "/captures/not-a-uuid",
        headers=auth_headers()
    )

    assert response.status_code == 422
    assert not database.exists()
