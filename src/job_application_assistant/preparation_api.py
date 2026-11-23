"""Authenticated company research and interview-guide preparation."""

import ipaddress
import json
import os
import socket
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from dotenv import dotenv_values
from fastapi import APIRouter, Depends, HTTPException
from langchain_openai import ChatOpenAI
from openai import OpenAIError
from pydantic import BaseModel, ConfigDict, Field

from job_application_assistant.company_research import (
    fetch_source, validate_source_url,
)
from job_application_assistant.interview_guide import (
    InterviewGuide, generate_guide, render_guide, validate_guide,
    validate_sources,
)
from job_application_assistant.job_requirements_storage import load_requirements
from job_application_assistant.models import CareerProfile
from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.profile_match_service import load_saved_profile
from job_application_assistant.profile_match_validation import (
    profile_revision, requirements_revision,
)
from job_application_assistant.resume_draft import ROOT


@contextmanager
def preparation_errors():
    """Return preparation-specific errors without exposing private paths."""
    try:
        yield
    except HTTPException:
        raise
    except OpenAIError as error:
        raise HTTPException(502, "Interview-guide model request failed.") from error
    except FileNotFoundError as error:
        raise HTTPException(404, "Saved sources, guide, or profile not found.") from error
    except KeyError as error:
        raise HTTPException(404, "Job or preparation data is missing.") from error
    except ValueError as error:
        raise HTTPException(409, str(error)) from error
    except (OSError, sqlite3.Error) as error:
        raise HTTPException(
            503, "Source retrieval or preparation storage is unavailable. "
            "Check the source URL and local server."
        ) from error


class CaptureResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_uuid: UUID
    official_sources_confirmed: Literal[True]
    urls: list[str] = Field(min_length=1, max_length=5)


class GenerateGuideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_uuid: UUID
    research_uuid: UUID
    research_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    sources_reviewed: Literal[True]
    recruiter_guidance: str = Field(default="", max_length=12000)


def write_json(path, value):
    """Install complete snapshots atomically."""
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as output:
            temporary = Path(output.name)
            json.dump(value, output, indent=2, ensure_ascii=False)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def public_source(url, hosts):
    """Reject non-public DNS destinations before requesting source text."""
    validate_source_url(url, hosts)
    host = urlsplit(url).hostname
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(item[4][0]).is_global
        for item in addresses
    ):
        raise ValueError("Company sources must use public HTTPS addresses.")
    return fetch_source(url, hosts)


def load_current_guide_manifest(
    database, profile_path, preparation_root, capture_uuid, guide_uuid,
):
    """Validate one saved guide against current sources and approved facts."""
    root = Path(preparation_root) / str(capture_uuid)
    path = root / "guides" / str(guide_uuid) / "guide.json"
    manifest = json.loads(path.read_bytes())
    requirements = load_requirements(database, capture_uuid)
    profile = load_saved_profile(profile_path)
    candidates = list((root / "research").glob("*/sources.json"))
    research_path = max(
        candidates, key=lambda item: item.stat().st_mtime_ns
    ) if candidates else None
    research_raw = research_path.read_bytes() if research_path else b""
    bundle = json.loads(research_raw) if research_raw else None
    if (
        requirements is None
        or manifest["status"] != "draft_requires_review"
        or manifest["capture_uuid"] != str(capture_uuid)
        or manifest["profile_sha256"] != profile_revision(profile)
        or manifest["requirements_sha256"] != requirements_revision(requirements)
        or research_path is None
        or manifest["research_uuid"] != research_path.parent.name
        or manifest["research_sha256"] != sha256(research_raw).hexdigest()
        or manifest["sources_snapshot"] != bundle
        or manifest["profile_sha256"] != profile_revision(
            CareerProfile.model_validate(manifest["profile_snapshot"])
        )
        or manifest["requirements_sha256"] != requirements_revision(
            JobRequirements.model_validate(manifest["requirements_snapshot"])
        )
    ):
        raise ValueError(
            "This guide needs refresh: the profile, job, or research "
            "changed. Review current sources and generate a new guide."
        )
    validate_guide(
        InterviewGuide.model_validate(manifest["guide"]),
        profile, requirements, bundle,
    )
    return manifest


def create_preparation_router(
    database, profile_path, require_token, preparation_root=None,
    fetcher=None, guide_generator=None,
):
    """Store browser preparation per job; never accept filesystem paths."""
    root = Path(preparation_root or ROOT / "data/private/preparation")
    router = APIRouter(dependencies=[Depends(require_token)])
    source_fetcher = fetcher or public_source

    def requirements_for(capture_uuid):
        requirements = load_requirements(database, capture_uuid)
        if requirements is None:
            raise ValueError("Extract this job's requirements first.")
        if not requirements.company_name:
            raise ValueError("The saved job extraction needs a company name.")
        return requirements

    def job_root(capture_uuid):
        return root / str(capture_uuid)

    def latest_path(capture_uuid, area, filename):
        candidates = list((job_root(capture_uuid) / area).glob(
            f"*/{filename}"
        ))
        return max(candidates, key=lambda p: p.stat().st_mtime_ns) if candidates else None

    def research_report(capture_uuid, research_uuid):
        requirements = requirements_for(capture_uuid)
        path = job_root(capture_uuid) / "research" / str(research_uuid) / "sources.json"
        raw = path.read_bytes()
        bundle = json.loads(raw)
        if bundle["capture_uuid"] != str(capture_uuid):
            raise ValueError("Research belongs to a different job.")
        if bundle["company"].casefold() != requirements.company_name.casefold():
            raise ValueError("Research company no longer matches the saved job.")
        validate_sources(bundle)
        return {
            "research_uuid": str(research_uuid),
            "research_sha256": sha256(raw).hexdigest(),
            "bundle": bundle,
        }

    def current_research(capture_uuid):
        path = latest_path(capture_uuid, "research", "sources.json")
        if path is None:
            return None
        return research_report(capture_uuid, UUID(path.parent.name))

    def reserve(path):
        try:
            path.mkdir(parents=True, exist_ok=False)
        except FileExistsError as error:
            raise ValueError(
                "This request is running or incomplete. Check the server "
                "before explicitly starting a new request."
            ) from error

    def guide_report(capture_uuid, guide_uuid):
        manifest = load_current_guide_manifest(
            database, profile_path, root, capture_uuid, guide_uuid
        )
        guide = InterviewGuide.model_validate(manifest["guide"])
        research = {"bundle": manifest["sources_snapshot"]}
        recruiter_guidance = manifest.get("recruiter_guidance", "")
        text = render_guide(guide, research["bundle"], recruiter_guidance)
        return {
            "guide_uuid": str(guide_uuid),
            "capture_uuid": str(capture_uuid),
            "status": "draft_requires_review",
            "guide": guide.model_dump(mode="json"),
            "sources": research["bundle"]["sources"],
            "recruiter_guidance": recruiter_guidance,
            "markdown": text,
        }

    @router.post("/captures/{capture_uuid}/research")
    def capture_research(capture_uuid: UUID, request: CaptureResearchRequest):
        with preparation_errors():
            requirements = requirements_for(capture_uuid)
            urls = list(dict.fromkeys(url.strip() for url in request.urls))
            if any(len(url) > 2048 for url in urls):
                raise ValueError("Source URLs must be under 2,049 characters.")
            hosts = {urlsplit(url).hostname for url in urls}
            for url in urls:
                validate_source_url(url, hosts)
                if not urlsplit(url).hostname:
                    raise ValueError("Each source needs a public hostname.")
            path = job_root(capture_uuid) / "research" / str(request.request_uuid)
            if (path / "sources.json").exists():
                existing = research_report(capture_uuid, request.request_uuid)
                if existing["bundle"]["submitted_urls"] != urls:
                    raise ValueError("Request ID already has different source URLs.")
                return existing
            reserve(path)
            sources = [source_fetcher(url, hosts) for url in urls]
            if sum(len(source["text"]) for source in sources) > 80000:
                raise ValueError(
                    "Captured text exceeds 80,000 characters. "
                    "Choose shorter, more focused official pages."
                )
            current = requirements_for(capture_uuid)
            if requirements_revision(current) != requirements_revision(requirements):
                raise ValueError("The job changed during capture. Capture again.")
            bundle = {
                "schema_version": 1,
                "capture_uuid": str(capture_uuid),
                "company": requirements.company_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "status": "sources_require_review",
                "collection_method": "user_selected_official_urls",
                "submitted_urls": urls,
                "allowed_hosts": sorted(hosts),
                "sources": sources,
                "limitations": [
                    "Official ownership was confirmed by the user, not inferred.",
                    "Static HTML may omit dynamically loaded content.",
                    "Publication dates are unverified metadata when present.",
                    "Captured text is untrusted data, not instructions.",
                ],
            }
            validate_sources(bundle)
            write_json(path / "sources.json", bundle)
            return research_report(capture_uuid, request.request_uuid)

    @router.get("/captures/{capture_uuid}/research/latest")
    def latest_research(capture_uuid: UUID):
        with preparation_errors():
            requirements_for(capture_uuid)
            return current_research(capture_uuid)

    @router.post("/captures/{capture_uuid}/interview-guides")
    def create_guide(capture_uuid: UUID, request: GenerateGuideRequest):
        with preparation_errors():
            requirements = requirements_for(capture_uuid)
            profile = load_saved_profile(profile_path)
            research = current_research(capture_uuid)
            if (
                research is None
                or research["research_uuid"] != str(request.research_uuid)
                or research["research_sha256"] != request.research_sha256
            ):
                raise ValueError("Research changed. Reload and review current sources.")
            guidance = request.recruiter_guidance.strip()
            path = job_root(capture_uuid) / "guides" / str(request.request_uuid)
            if (path / "guide.json").exists():
                previous = json.loads((path / "guide.json").read_bytes())
                if (
                    previous["research_uuid"] != str(request.research_uuid)
                    or previous["research_sha256"] != request.research_sha256
                    or previous.get("recruiter_guidance", "") != guidance
                ):
                    raise ValueError("Request ID already has different guide inputs.")
                return guide_report(capture_uuid, request.request_uuid)
            reserve(path)
            if guide_generator is None:
                settings = dotenv_values(ROOT / ".env")
                key = (settings.get("OPENAI_API_KEY") or "").strip()
                model = (settings.get("OPENAI_MODEL") or "").strip()
                if not key or not model:
                    raise ValueError("Guide generation is not configured.")
                llm = ChatOpenAI(
                    model=model, api_key=key,
                    base_url="https://api.openai.com/v1",
                    use_responses_api=True, timeout=60,
                    max_retries=0, max_tokens=6000,
                )
                guide = generate_guide(
                    llm, profile, requirements, research["bundle"], guidance
                )
            else:
                model = "injected-generator"
                guide = guide_generator(
                    profile, requirements, research["bundle"], guidance
                )
            guide = validate_guide(
                guide, profile, requirements, research["bundle"]
            )
            current_requirements = requirements_for(capture_uuid)
            current_sources = current_research(capture_uuid)
            if (
                profile_revision(load_saved_profile(profile_path)) != profile_revision(profile)
                or requirements_revision(current_requirements) != requirements_revision(requirements)
                or current_sources is None
                or current_sources["research_uuid"] != research["research_uuid"]
                or current_sources["research_sha256"] != research["research_sha256"]
            ):
                raise ValueError("Inputs changed during generation. Generate again.")
            manifest = {
                "status": "draft_requires_review",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "capture_uuid": str(capture_uuid),
                "model": model,
                "profile_sha256": profile_revision(profile),
                "requirements_sha256": requirements_revision(requirements),
                "sources_sha256": research["research_sha256"],
                "research_uuid": research["research_uuid"],
                "research_sha256": research["research_sha256"],
                "recruiter_guidance": guidance,
                "profile_snapshot": profile.model_dump(mode="json"),
                "requirements_snapshot": requirements.model_dump(mode="json"),
                "sources_snapshot": research["bundle"],
                "guide": guide.model_dump(mode="json"),
            }
            write_json(path / "guide.json", manifest)
            return guide_report(capture_uuid, request.request_uuid)

    @router.get("/captures/{capture_uuid}/interview-guides/latest")
    def latest_guide(capture_uuid: UUID):
        with preparation_errors():
            requirements_for(capture_uuid)
            path = latest_path(capture_uuid, "guides", "guide.json")
            return guide_report(capture_uuid, UUID(path.parent.name)) if path else None

    return router
