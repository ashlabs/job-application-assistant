"""Authenticated resume generation, review, approval, and export."""

import base64
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Literal
from uuid import UUID

from dotenv import dotenv_values
from fastapi import APIRouter, Depends, HTTPException
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from job_application_assistant.job_requirements_storage import load_requirements
from job_application_assistant.profile_match_service import load_saved_profile
from job_application_assistant.profile_match_validation import (
    profile_revision, requirements_revision,
)
from job_application_assistant.resume_draft import (
    ROOT, render_resume, select_resume_records, validate_selection,
)
from job_application_assistant.resume_export import render_documents
from job_application_assistant.resume_review import (
    approve_draft, review_draft, verify_approval,
)


class GenerateResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_uuid: UUID
    name: str = Field(min_length=1, max_length=120)


class ApproveResumeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: Literal[True]
    review_token: str = Field(pattern=r"^[a-f0-9]{64}$")


@contextmanager
def resume_errors():
    """Return useful errors without exposing private server paths."""
    try:
        yield
    except HTTPException:
        raise
    except OpenAIError as error:
        raise HTTPException(502, "Resume model request failed.") from error
    except FileNotFoundError as error:
        raise HTTPException(404, "Resume or approved profile not found.") from error
    except KeyError as error:
        raise HTTPException(404, "Job or resume data is missing.") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise HTTPException(503, "Resume storage is unavailable.") from error


def create_resume_router(database, profile_path, require_token,
                         resume_root=None, selector=None):
    """Keep paths server-controlled and permit fake selectors in tests."""
    root = Path(resume_root or ROOT / "data/private/resumes")
    router = APIRouter(dependencies=[Depends(require_token)])

    def inputs(capture_uuid):
        requirements = load_requirements(database, capture_uuid)
        if requirements is None:
            raise ValueError("Extract requirements before preparing a resume.")
        return load_saved_profile(profile_path), requirements

    def directory(capture_uuid, resume_uuid):
        # Typed UUIDs cannot introduce arbitrary filesystem paths.
        return root / str(capture_uuid) / str(resume_uuid)

    def report(capture_uuid, resume_uuid):
        profile, requirements = inputs(capture_uuid)
        path = directory(capture_uuid, resume_uuid)
        review = review_draft(path, profile, requirements)
        approved = False
        if (path / "approval.json").exists():
            verify_approval(path, profile, requirements)
            approved = True
        manifest = json.loads((path / "evidence.json").read_text())
        return {
            "resume_uuid": str(resume_uuid),
            "capture_uuid": str(capture_uuid),
            "text": review["text"],
            "review_token": review["review_token"],
            "approved": approved,
            "evidence": {
                "selection": manifest["selection"],
                "approved_source_snapshot": manifest[
                    "approved_source_snapshot"
                ],
            },
        }

    @router.post("/captures/{capture_uuid}/resumes")
    def generate(capture_uuid: UUID, request: GenerateResumeRequest):
        with resume_errors():
            name = request.name.strip()
            if not name or "\n" in name or "\r" in name:
                raise ValueError("Enter a candidate name on one line.")
            profile, requirements = inputs(capture_uuid)
            path = directory(capture_uuid, request.request_uuid)
            if path.exists():
                if not (path / "resume.txt").exists():
                    raise ValueError(
                        "This generation is running or incomplete. "
                        "Check the server before starting a new request."
                    )
                existing = report(capture_uuid, request.request_uuid)
                if existing["text"].splitlines()[0] != name:
                    raise ValueError("Request ID already has a different name.")
                return existing
            try:
                path.mkdir(parents=True, exist_ok=False)
            except FileExistsError as error:
                raise ValueError("This generation request is already running.") from error

            if selector is None:
                settings = dotenv_values(ROOT / ".env")
                key = (settings.get("OPENAI_API_KEY") or "").strip()
                model = (settings.get("OPENAI_MODEL") or "").strip()
                if not key or not model:
                    raise ValueError("Resume generation is not configured.")
                llm = ChatOpenAI(
                    model=model, api_key=key,
                    base_url="https://api.openai.com/v1",
                    use_responses_api=True, timeout=60,
                    max_retries=0, max_tokens=4096,
                )
                selection = select_resume_records(llm, profile, requirements)
            else:
                model = "injected-selector"
                selection = selector(profile, requirements)
            selection = validate_selection(profile, selection)
            text = render_resume(profile, selection, name)
            current_profile, current_requirements = inputs(capture_uuid)
            if (
                profile_revision(current_profile) != profile_revision(profile)
                or requirements_revision(current_requirements)
                != requirements_revision(requirements)
            ):
                raise ValueError("Sources changed. Generate a new draft.")
            manifest = {
                "status": "draft_requires_review",
                "capture_uuid": str(capture_uuid),
                "profile_sha256": profile_revision(profile),
                "requirements_sha256": requirements_revision(requirements),
                "model": model,
                "selection": selection.model_dump(mode="json"),
                "approved_source_snapshot": profile.model_dump(mode="json"),
                "requirements_snapshot": requirements.model_dump(mode="json"),
            }
            (path / "evidence.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            (path / "resume.txt").write_text(text, encoding="utf-8")
            return report(capture_uuid, request.request_uuid)

    @router.get("/captures/{capture_uuid}/resumes/latest")
    def latest(capture_uuid: UUID):
        with resume_errors():
            inputs(capture_uuid)
            parent = root / str(capture_uuid)
            candidates = list(parent.glob("*/resume.txt"))
            if not candidates:
                return None
            newest = max(candidates, key=lambda path: path.stat().st_mtime_ns)
            return report(capture_uuid, UUID(newest.parent.name))

    @router.post("/captures/{capture_uuid}/resumes/{resume_uuid}/approve")
    def approve(capture_uuid: UUID, resume_uuid: UUID,
                request: ApproveResumeRequest):
        with resume_errors():
            profile, requirements = inputs(capture_uuid)
            path = directory(capture_uuid, resume_uuid)
            review = review_draft(path, profile, requirements)
            if review["review_token"] != request.review_token:
                raise ValueError("Draft changed. Reload and review it again.")
            if (path / "approval.json").exists():
                verify_approval(path, profile, requirements)
            else:
                try:
                    approve_draft(path, profile, requirements,
                                  request.review_token)
                except FileExistsError:
                    verify_approval(path, profile, requirements)
            return report(capture_uuid, resume_uuid)

    @router.post("/captures/{capture_uuid}/resumes/{resume_uuid}/export")
    def export(capture_uuid: UUID, resume_uuid: UUID,
               request: ApproveResumeRequest):
        with resume_errors():
            profile, requirements = inputs(capture_uuid)
            path = directory(capture_uuid, resume_uuid)
            review = review_draft(path, profile, requirements)
            if review["review_token"] != request.review_token:
                raise ValueError("Draft changed. Reload and review it again.")
            text = verify_approval(path, profile, requirements)
            documents = render_documents(text)
            profile, requirements = inputs(capture_uuid)
            if verify_approval(path, profile, requirements) != text:
                raise ValueError("Sources changed during export.")
            return {
                "files": {
                    name: base64.b64encode(content).decode("ascii")
                    for name, content in documents.items()
                }
            }

    return router
