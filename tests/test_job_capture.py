"""Validation tests for job-description captures."""

from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from job_application_assistant.job_capture import JobCapture


def capture_data(**updates):
    """Return a fictional capture with explicit source metadata."""
    data = {
        "capture_uuid": str(uuid4()),
        "source_url": "https://example.com/jobs/product-manager",
        "page_title": "Product Manager — Example Company",
        "captured_at": "2026-11-17T14:30:00-08:00",
        "capture_method": "selection",
        "jd_text": "Lead product discovery and prioritize customer needs."
    }
    data.update(updates)
    return data


def test_json_round_trip_preserves_capture_and_metadata():
    data = capture_data()
    capture = JobCapture.model_validate(data)

    restored = JobCapture.model_validate_json(
        capture.model_dump_json()
    )

    assert restored == capture
    assert restored.capture_uuid == UUID(data["capture_uuid"])
    assert str(restored.source_url) == data["source_url"]
    assert restored.page_title == data["page_title"]
    assert restored.captured_at.utcoffset() == timedelta(hours=-8)
    assert restored.capture_method == "selection"
    assert restored.jd_text == data["jd_text"]


@pytest.mark.parametrize("method", ["page", "selection", "paste"])
def test_supported_capture_methods(method):
    capture = JobCapture.model_validate(
        capture_data(capture_method=method)
    )

    assert capture.capture_method == method


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_url", "file:///tmp/job.html"),
        ("source_url", "not a URL"),
        ("captured_at", "2026-11-17T14:30:00"),
        ("capture_method", "unknown"),
        ("jd_text", " \n\t "),
        ("page_title", "   ")
    ],
)
def test_invalid_capture_rejected(field, value):
    with pytest.raises(ValidationError):
        JobCapture.model_validate(capture_data(**{field: value}))


def test_missing_capture_time_rejected():
    data = capture_data()
    del data["captured_at"]

    with pytest.raises(ValidationError):
        JobCapture.model_validate(data)


def test_missing_page_title_remains_unknown():
    data = capture_data()
    del data["page_title"]

    capture = JobCapture.model_validate(data)

    assert capture.page_title is None


def test_unexpected_fields_rejected():
    with pytest.raises(ValidationError):
        JobCapture.model_validate(
            capture_data(unexpected_field="Not supported")
        )