"""Authenticated extraction and retrieval of saved JD requirements."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError

from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_capture_storage import load_capture
from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.job_requirements_agent import (
    MAX_JD_CHARACTERS
)
from job_application_assistant.job_requirements_service import (
    ExtractionConfigurationError
)
from job_application_assistant.job_requirements_storage import (
    load_requirements,
    save_requirements
)
from job_application_assistant.job_requirements_validation import (
    validate_requirements
)


RequirementsExtractor = Callable[[JobCapture], JobRequirements]


def create_requirements_router(
    database: Path,
    require_token: Callable,
    extractor: RequirementsExtractor
) -> APIRouter:
    """Build routes with an injectable extractor for offline testing."""
    router = APIRouter(
        dependencies=[Depends(require_token)]
    )

    def read_saved(capture_uuid: UUID) -> JobRequirements | None:
        """Read stored results and translate storage errors."""
        try:
            return load_requirements(database, capture_uuid)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="Capture not found."
            ) from error
        except (sqlite3.Error, OSError) as error:
            raise HTTPException(
                status_code=503,
                detail="Capture storage is unavailable. Retry later."
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=500,
                detail="Stored requirement or capture data could not be read."
            ) from error

    @router.get(
        "/captures/{capture_uuid}/requirements",
        response_model=JobRequirements | None
    )
    def get_requirements(
        capture_uuid: UUID
    ) -> JobRequirements | None:
        """Return stored requirements, or null if not yet extracted."""
        return read_saved(capture_uuid)

    @router.post(
        "/captures/{capture_uuid}/requirements",
        response_model=JobRequirements
    )
    def extract_requirements(capture_uuid: UUID) -> JobRequirements:
        """Reuse saved requirements or extract and persist them."""
        existing = read_saved(capture_uuid)
        if existing is not None:
            return existing

        try:
            capture = load_capture(database, capture_uuid)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="Capture not found.",
            ) from error
        except (sqlite3.Error, OSError) as error:
            raise HTTPException(
                status_code=503,
                detail="Capture storage is unavailable. Retry later."
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=500,
                detail="Stored capture data could not be read."
            ) from error

        if len(capture.jd_text) > MAX_JD_CHARACTERS:
            raise HTTPException(
                status_code=422,
                detail=(
                    "The JD exceeds the extraction limit of 60,000 "
                    "characters. Capture only the relevant JD text."
                )
            )

        try:
            result = extractor(capture)
            validated = validate_requirements(capture, result)
        except ExtractionConfigurationError as error:
            raise HTTPException(
                status_code=503,
                detail="Requirement extraction is not configured."
            ) from error
        except OpenAIError as error:
            raise HTTPException(
                status_code=502,
                detail=(
                    "The model request failed. "
                    "No extraction result was accepted."
                )
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=502,
                detail=(
                    "The extraction failed validation. "
                    "No extraction result was accepted."
                )
            ) from error

        try:
            return save_requirements(database, validated)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="Capture not found."
            ) from error
        except (sqlite3.Error, OSError) as error:
            raise HTTPException(
                status_code=503,
                detail=(
                    "The extraction could not be saved. "
                    "Check storage before retrying."
                )
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=500,
                detail="The extraction could not be stored safely."
            ) from error

    return router