"""Tests for authenticated, on-demand requirement extraction."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from openai import OpenAIError

from job_application_assistant.capture_api import create_app
from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_capture_storage import (
    load_capture,
    save_capture
)
from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.job_requirements_service import (
    ExtractionConfigurationError
)
from job_application_assistant.job_requirements_validation import (
    jd_text_revision
)


TOKEN = "local-extraction-test-token"
HEADERS = {"X-Capture-Token": TOKEN}


class FakeExtractor:
    """Record calls and return valid, invalid, or failed extraction."""

    def __init__(self):
        self.calls = []
        self.error = None
        self.invalid_excerpt = False

    def __call__(self, capture):
        self.calls.append(capture)

        if self.error is not None:
            raise self.error

        return JobRequirements(
            capture_uuid=capture.capture_uuid,
            jd_text_sha256=jd_text_revision(capture.jd_text),
            requirements=[
                JobRequirement(
                    description="Experience conducting customer interviews.",
                    kind="qualification",
                    importance="required",
                    source_excerpt=(
                        "Invented source text."
                        if self.invalid_excerpt
                        else capture.jd_text
                    )
                )
            ]
        )


@pytest.fixture
def extraction_api(tmp_path):
    database = tmp_path / "captures.sqlite"
    capture = JobCapture(
        source_url="https://example.com/jobs/product-manager",
        captured_at="2026-11-18T10:00:00-08:00",
        capture_method="paste",
        jd_text="Required: Experience conducting customer interviews."
    )
    save_capture(database, capture)

    extractor = FakeExtractor()
    app = create_app(
        database_path=database,
        api_token=TOKEN,
        requirements_extractor=extractor
    )

    with TestClient(app) as client:
        yield client, database, capture, extractor


def test_explicit_post_extracts_without_changing_capture(extraction_api):
    client, database, capture, extractor = extraction_api

    response = client.post(
        f"/captures/{capture.capture_uuid}/requirements",
        headers=HEADERS
    )

    assert response.status_code == 200
    result = JobRequirements.model_validate(response.json())
    assert result.capture_uuid == capture.capture_uuid
    assert len(result.requirements) == 1
    assert extractor.calls == [capture]
    assert load_capture(database, capture.capture_uuid) == capture


def test_listing_and_opening_capture_do_not_extract(extraction_api):
    client, _, capture, extractor = extraction_api

    listing = client.get("/captures", headers=HEADERS)
    detail = client.get(
        f"/captures/{capture.capture_uuid}",
        headers=HEADERS
    )

    assert listing.status_code == 200
    assert detail.status_code == 200
    assert extractor.calls == []


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_extraction_requires_token(extraction_api, token):
    client, _, capture, extractor = extraction_api
    headers = {} if token is None else {"X-Capture-Token": token}

    response = client.post(
        f"/captures/{capture.capture_uuid}/requirements",
        headers=headers
    )

    assert response.status_code == 401
    assert extractor.calls == []


def test_missing_capture_does_not_call_extractor(extraction_api):
    client, _, _, extractor = extraction_api

    response = client.post(
        f"/captures/{uuid4()}/requirements",
        headers=HEADERS
    )

    assert response.status_code == 404
    assert extractor.calls == []


@pytest.mark.parametrize(
    ("error", "expected_status"),
    [
        (ExtractionConfigurationError("Missing settings"), 503),
        (OpenAIError("Simulated provider failure"), 502),
        (ValueError("Invalid extraction"), 502)
    ]
)
def test_extraction_failures_preserve_capture(
    extraction_api,
    error,
    expected_status
):
    client, database, capture, extractor = extraction_api
    extractor.error = error

    response = client.post(
        f"/captures/{capture.capture_uuid}/requirements",
        headers=HEADERS
    )

    assert response.status_code == expected_status
    assert len(extractor.calls) == 1
    assert load_capture(database, capture.capture_uuid) == capture


def test_api_rejects_result_with_unsupported_excerpt(extraction_api):
    client, database, capture, extractor = extraction_api
    extractor.invalid_excerpt = True

    response = client.post(
        f"/captures/{capture.capture_uuid}/requirements",
        headers=HEADERS
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The extraction failed validation. "
        "No extraction result was accepted."
    )
    assert load_capture(database, capture.capture_uuid) == capture

def test_get_before_extraction_returns_null_without_model_call(
    extraction_api,
):
    client, _, capture, extractor = extraction_api

    response = client.get(
        f"/captures/{capture.capture_uuid}/requirements",
        headers=HEADERS,
    )

    assert response.status_code == 200
    assert response.json() is None
    assert extractor.calls == []


def test_repeated_post_and_get_reuse_saved_result(extraction_api):
    client, _, capture, extractor = extraction_api
    path = f"/captures/{capture.capture_uuid}/requirements"

    first = client.post(path, headers=HEADERS)
    assert first.status_code == 200

    # Any subsequent model call would fail this test.
    extractor.error = AssertionError("Unexpected additional model call")

    repeated = client.post(path, headers=HEADERS)
    restored = client.get(path, headers=HEADERS)

    assert repeated.status_code == 200
    assert restored.status_code == 200
    assert repeated.json() == first.json()
    assert restored.json() == first.json()
    assert len(extractor.calls) == 1


@pytest.mark.parametrize("token", [None, "wrong-token"])
def test_saved_requirements_get_requires_token(extraction_api, token):
    client, _, capture, extractor = extraction_api
    path = f"/captures/{capture.capture_uuid}/requirements"
    client.post(path, headers=HEADERS)
    headers = {} if token is None else {"X-Capture-Token": token}

    response = client.get(path, headers=headers)

    assert response.status_code == 401
    assert len(extractor.calls) == 1


def test_get_requirements_for_missing_capture_returns_not_found(
    extraction_api
):
    client, _, _, extractor = extraction_api

    response = client.get(
        f"/captures/{uuid4()}/requirements",
        headers=HEADERS
    )

    assert response.status_code == 404
    assert extractor.calls == []