"""Tests for persistent job captures and safe retries."""

import sqlite3
from uuid import uuid4

import pytest

from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_capture_storage import (
    CaptureConflictError,
    load_capture,
    save_capture,
    list_captures
)


def make_capture():
    """Create a fictional capture."""
    return JobCapture(
        source_url="https://example.com/jobs/product-manager",
        page_title="Product Manager",
        captured_at="2026-11-17T14:30:00-08:00",
        capture_method="selection",
        jd_text="Lead product discovery and prioritize customer needs."
    )


def test_capture_survives_database_reopening(tmp_path):
    database = tmp_path / "captures.sqlite"
    capture = make_capture()

    assert save_capture(database, capture) is True

    # Each function opens and closes its own connection.
    restored = load_capture(database, capture.capture_uuid)

    assert restored == capture


def test_identical_retry_does_not_create_duplicate(tmp_path):
    database = tmp_path / "captures.sqlite"
    capture = make_capture()
    retry = JobCapture.model_validate_json(capture.model_dump_json())

    assert save_capture(database, capture) is True
    assert save_capture(database, retry) is False

    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM job_captures"
        ).fetchone()[0]

    assert count == 1
    assert load_capture(database, capture.capture_uuid) == capture


def test_conflicting_retry_preserves_original_capture(tmp_path):
    database = tmp_path / "captures.sqlite"
    original = make_capture()
    save_capture(database, original)

    changed_data = original.model_dump(mode="json")
    changed_data["jd_text"] = "Different job-description content."
    changed = JobCapture.model_validate(changed_data)

    with pytest.raises(CaptureConflictError):
        save_capture(database, changed)

    assert load_capture(database, original.capture_uuid) == original


def test_missing_capture_raises_key_error(tmp_path):
    database = tmp_path / "captures.sqlite"
    save_capture(database, make_capture())

    with pytest.raises(KeyError):
        load_capture(database, uuid4())


def test_loading_missing_database_does_not_create_it(tmp_path):
    database = tmp_path / "missing.sqlite"

    with pytest.raises(KeyError):
        load_capture(database, uuid4())

    assert not database.exists()

def test_listing_missing_database_returns_empty_without_creating_it(tmp_path):
    database = tmp_path / "missing.sqlite"

    assert list_captures(database) == []
    assert not database.exists()


def test_listing_preserves_captures_and_orders_by_actual_time(tmp_path):
    database = tmp_path / "captures.sqlite"

    older_data = make_capture().model_dump(mode="json")
    older_data["captured_at"] = "2026-11-18T10:00:00+02:00"
    older = JobCapture.model_validate(older_data)

    newer_data = make_capture().model_dump(mode="json")
    newer_data["captured_at"] = "2026-11-18T07:00:00-08:00"
    newer = JobCapture.model_validate(newer_data)

    # Insert newest first so insertion order cannot explain the result.
    save_capture(database, newer)
    save_capture(database, older)

    captures = list_captures(database)

    # 07:00 at UTC-8 is later than 10:00 at UTC+2.
    assert captures == [newer, older]
    assert load_capture(database, older.capture_uuid) == older
    assert load_capture(database, newer.capture_uuid) == newer
