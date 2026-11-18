"""Local API for saving and retrieving job-description captures."""

import sqlite3
from pathlib import Path
from secrets import compare_digest
from typing import Literal
from uuid import UUID

from dotenv import dotenv_values
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from job_application_assistant.job_capture import JobCapture
from job_application_assistant.job_capture_storage import (
    CaptureConflictError,
    list_captures,
    load_capture,
    save_capture
)
from job_application_assistant.job_requirements_api import (
    RequirementsExtractor,
    create_requirements_router
)
from job_application_assistant.job_requirements_service import (
    extract_capture_requirements
)


ROOT = Path(__file__).resolve().parents[2]


class SubmittedCapture(JobCapture):
    """Require the caller's UUID so retries retain their identity."""

    capture_uuid: UUID = Field(...)


class CaptureRequest(BaseModel):
    """A capture explicitly confirmed through the interface."""

    model_config = ConfigDict(extra="forbid")

    confirmed: Literal[True]
    capture: SubmittedCapture


class CaptureReceipt(BaseModel):
    """Report whether a capture was newly saved or already present."""

    capture_uuid: UUID
    status: Literal["created", "already_saved"]


def create_app(
    database_path: Path | None = None,
    api_token: str | None = None,
    requirements_extractor: RequirementsExtractor = (
        extract_capture_requirements
    )
) -> FastAPI:
    """Build the local capture API."""
    if api_token is None:
        settings = dotenv_values(ROOT / ".env")
        api_token = settings.get("CAPTURE_API_TOKEN")

    token = (api_token or "").strip()
    if not token:
        raise ValueError("Set CAPTURE_API_TOKEN in the project's .env file.")

    database = (
        database_path
        if database_path is not None
        else ROOT / "data/private/job_captures.sqlite"
    )

    app = FastAPI(
        title="Job Application Assistant Capture API",
        docs_url=None,
        redoc_url=None,
        openapi_url=None
    )

    def require_token(
        x_capture_token: str | None = Header(default=None)
    ) -> None:
        """Accept requests carrying the locally configured token."""
        supplied = (x_capture_token or "").encode("utf-8")
        expected = token.encode("utf-8")

        if not compare_digest(supplied, expected):
            raise HTTPException(
                status_code=401,
                detail="Invalid or missing capture token."
            )

    @app.post(
        "/captures",
        response_model=CaptureReceipt,
        dependencies=[Depends(require_token)]
    )
    def capture_job(
        request: CaptureRequest,
        response: Response
    ) -> CaptureReceipt:
        """Validate and save a confirmed capture without model calls."""
        try:
            created = save_capture(database, request.capture)
        except CaptureConflictError as error:
            raise HTTPException(
                status_code=409,
                detail=str(error)
            ) from error
        except (sqlite3.Error, OSError) as error:
            raise HTTPException(
                status_code=503,
                detail="Capture storage is unavailable. Retry later."
            ) from error

        response.status_code = 201 if created else 200

        return CaptureReceipt(
            capture_uuid=request.capture.capture_uuid,
            status="created" if created else "already_saved"
        )

    @app.get(
        "/captures",
        response_model=list[JobCapture],
        dependencies=[Depends(require_token)],
    )
    def get_captures() -> list[JobCapture]:
        """List saved captures, newest first."""
        try:
            return list_captures(database)
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

    @app.get(
        "/captures/{capture_uuid}",
        response_model=JobCapture,
        dependencies=[Depends(require_token)]
    )
    def get_capture(capture_uuid: UUID) -> JobCapture:
        """Retrieve one saved capture."""
        try:
            return load_capture(database, capture_uuid)
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
                detail="Stored capture data could not be read."
            ) from error

    app.include_router(
        create_requirements_router(
            database=database,
            require_token=require_token,
            extractor=requirements_extractor
        )
    )
    
    return app