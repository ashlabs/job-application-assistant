"""Authenticated assessment against a server-configured saved profile."""

import sqlite3
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from openai import OpenAIError

from job_application_assistant.job_requirements_storage import (
    load_requirements
)
from job_application_assistant.profile_match_service import (
    MatchConfigurationError,
    ProfileAssessor,
    ProfileMatchReport,
    assess_saved_profile,
    load_saved_profile
)
from job_application_assistant.profile_match_validation import (
    requirements_revision
)


def create_profile_match_router(
    database: Path,
    profile_path: Path,
    require_token: Callable,
    assessor: ProfileAssessor | None = None
) -> APIRouter:
    """Build assessment routes without accepting client-supplied paths."""
    router = APIRouter(
        dependencies=[Depends(require_token)]
    )

    def read_requirements(capture_uuid: UUID):
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
                detail="Capture storage is unavailable."
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=500,
                detail="Stored requirements could not be read safely."
            ) from error

    @router.post(
        "/captures/{capture_uuid}/profile-match",
        response_model=ProfileMatchReport
    )
    def assess_match(capture_uuid: UUID) -> ProfileMatchReport:
        """Assess stored requirements against the configured profile."""
        requirements = read_requirements(capture_uuid)

        if requirements is None:
            raise HTTPException(
                status_code=409,
                detail="Extract requirements before assessing profile match."
            )

        # Check the saved profile before making any model request.
        try:
            load_saved_profile(profile_path)
        except FileNotFoundError as error:
            raise HTTPException(
                status_code=409,
                detail="No saved career profile is configured at this path."
            ) from error
        except OSError as error:
            raise HTTPException(
                status_code=503,
                detail="The saved career profile is unavailable."
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=422,
                detail="The saved career profile is invalid."
            ) from error

        try:
            report = assess_saved_profile(
                profile_path,
                requirements,
                assessor=assessor
            )
        except MatchConfigurationError as error:
            raise HTTPException(
                status_code=503,
                detail="Profile matching is not configured."
            ) from error
        except OpenAIError as error:
            raise HTTPException(
                status_code=502,
                detail="The model request failed. No match report was accepted."
            ) from error
        except OSError as error:
            raise HTTPException(
                status_code=503,
                detail="The saved career profile became unavailable."
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=502,
                detail=(
                    "Assessment validation failed or the saved profile "
                    "changed. No match report was accepted."
                )
            ) from error

        current_requirements = read_requirements(capture_uuid)
        if (
            current_requirements is None
            or requirements_revision(current_requirements)
            != report.match.requirements_sha256
        ):
            raise HTTPException(
                status_code=409,
                detail="Requirements changed during assessment. Assess again."
            )

        return report

    return router