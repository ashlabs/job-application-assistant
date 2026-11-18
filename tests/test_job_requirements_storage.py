"""Tests for persistent, source-validated requirement extractions."""

import sqlite3

import pytest

from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_capture_storage import save_capture
from job_application_assistant.job_requirements import (
    JobRequirement,
    JobRequirements
)
from job_application_assistant.job_requirements_storage import (
    load_requirements,
    save_requirements
)
from job_application_assistant.job_requirements_validation import (
    jd_text_revision
)


@pytest.fixture
def saved_capture(tmp_path):
    database = tmp_path / "captures.sqlite"
    capture = JobCapture(
        source_url="https://example.com/jobs/product-manager",
        captured_at="2026-11-18T12:00:00-08:00",
        capture_method="paste",
        jd_text="Required: Experience conducting customer interviews."
    )
    save_capture(database, capture)
    return database, capture


def make_extraction(capture):
    return JobRequirements(
        capture_uuid=capture.capture_uuid,
        jd_text_sha256=jd_text_revision(capture.jd_text),
        requirements=[
            JobRequirement(
                description="Experience conducting customer interviews.",
                kind="qualification",
                importance="required",
                source_excerpt=capture.jd_text
            )
        ]
    )


def test_extraction_survives_database_reopening(saved_capture):
    database, capture = saved_capture
    extraction = make_extraction(capture)

    saved = save_requirements(database, extraction)
    restored = load_requirements(database, capture.capture_uuid)

    assert saved == extraction
    assert restored == extraction


def test_capture_without_extraction_returns_none(saved_capture):
    database, capture = saved_capture

    assert load_requirements(database, capture.capture_uuid) is None


def test_later_extraction_does_not_replace_first_result(saved_capture):
    database, capture = saved_capture
    first = make_extraction(capture)
    save_requirements(database, first)

    later = make_extraction(capture)
    later.requirements[0].description = (
        "Prior experience interviewing customers."
    )

    returned = save_requirements(database, later)

    assert returned == first
    assert load_requirements(database, capture.capture_uuid) == first

    with sqlite3.connect(database) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM job_requirements"
        ).fetchone()[0]

    assert count == 1


def test_invalid_extraction_does_not_create_storage_table(saved_capture):
    database, capture = saved_capture
    extraction = make_extraction(capture)
    extraction.requirements[0].source_excerpt = "Invented source text."

    with pytest.raises(ValueError, match="excerpt absent"):
        save_requirements(database, extraction)

    with sqlite3.connect(database) as connection:
        table = connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name = 'job_requirements'
            """
        ).fetchone()

    assert table is None


def test_loaded_extraction_is_revalidated_against_source(saved_capture):
    database, capture = saved_capture
    extraction = make_extraction(capture)
    save_requirements(database, extraction)

    damaged = extraction.model_dump(mode="json")
    damaged["requirements"][0]["source_excerpt"] = "Invented source text."
    damaged_payload = JobRequirements.model_validate(
        damaged
    ).model_dump_json()

    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            UPDATE job_requirements
            SET payload = ?
            WHERE capture_uuid = ? AND jd_text_sha256 = ?
            """,
            (
                damaged_payload,
                str(capture.capture_uuid),
                extraction.jd_text_sha256
            )
        )

    with pytest.raises(ValueError, match="excerpt absent"):
        load_requirements(database, capture.capture_uuid)