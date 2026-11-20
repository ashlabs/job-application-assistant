"""Authenticated browser coaching using the existing checkpointed workflow."""

import fcntl
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal
from uuid import UUID

from dotenv import dotenv_values
from fastapi import APIRouter, Depends
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.sqlite import SqliteSaver
from pydantic import BaseModel, ConfigDict, Field

from job_application_assistant.interview_coaching import (
    apply_coaching_command, build_coaching_graph,
    create_coaching_step, new_coaching_state,
)
from job_application_assistant.job_capture_storage import load_capture
from job_application_assistant.preparation_api import (
    load_current_guide_manifest, preparation_errors, write_json,
)
from job_application_assistant.resume_draft import ROOT


class StartCoachingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_uuid: UUID
    guide_uuid: UUID
    confirmed: Literal[True]


class CoachingActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_uuid: UUID
    expected_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    action: Literal["answer", "next", "retry", "skip", "pause", "resume"]
    answer: str = Field(default="", max_length=12000)


def state_revision(state):
    """Detect updates from another tab before applying a command."""
    return sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


@contextmanager
def session_lock(directory):
    """Serialize mutations across server threads and cooperating processes."""
    with (directory / ".session.lock").open("a") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(
                "Another coaching operation is running. Wait, then reload the session."
            ) from error
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def create_coaching_router(
    database, profile_path, require_token, preparation_root=None,
    coaching_root=None, coaching_step=None,
):
    """Expose coaching without accepting client file paths or profile edits."""
    preparation = Path(preparation_root or ROOT / "data/private/preparation")
    root = Path(coaching_root or ROOT / "data/private/browser_coaching")
    router = APIRouter(dependencies=[Depends(require_token)])

    def directory(capture_uuid, session_uuid):
        load_capture(database, capture_uuid)
        return root / str(capture_uuid) / str(session_uuid)

    def metadata_for(path):
        return json.loads((path / "session.json").read_bytes())

    def latest_guide(capture_uuid):
        candidates = list((preparation / str(capture_uuid) / "guides").glob("*/guide.json"))
        if not candidates:
            raise ValueError("Generate and review an interview guide first.")
        path = max(candidates, key=lambda item: item.stat().st_mtime_ns)
        return UUID(path.parent.name)

    def configured_step():
        if coaching_step is not None:
            return coaching_step
        settings = dotenv_values(ROOT / ".env")
        key = (settings.get("OPENAI_API_KEY") or "").strip()
        model = (settings.get("OPENAI_MODEL") or "").strip()
        if not key or not model:
            raise ValueError("Coaching is not configured.")
        return create_coaching_step(ChatOpenAI(
            model=model, api_key=key, base_url="https://api.openai.com/v1",
            use_responses_api=True, timeout=60, max_retries=0, max_tokens=4096,
        ))

    def context_outdated(metadata):
        try:
            capture_uuid = UUID(metadata["capture_uuid"])
            guide_uuid = UUID(metadata["guide_uuid"])
            if latest_guide(capture_uuid) != guide_uuid:
                return True
            current = load_current_guide_manifest(
                database, profile_path, preparation, capture_uuid, guide_uuid
            )
            return state_revision(current) != metadata["guide_sha256"]
        except (ValueError, KeyError, OSError):
            return True

    def report(path, state):
        if not state:
            raise ValueError("Session initialization is incomplete. Start a new session.")
        metadata = metadata_for(path)
        evaluated = [
            event for event in state["history"]
            if event["event"] == "evaluated"
            and event["question_number"] == state["index"] + 1
        ]
        complete = state["status"] == "complete"
        return {
            "session_uuid": path.name,
            "capture_uuid": metadata["capture_uuid"],
            "guide_uuid": metadata["guide_uuid"],
            "created_at": metadata["created_at"],
            "revision": state_revision(state),
            "status": state["status"], "phase": state["phase"],
            "question_number": min(state["index"] + 1, 5),
            "question": None if complete else state["questions"][state["index"]],
            "followup_question": state["followup_question"],
            "request_count": state["request_count"],
            "latest_feedback": evaluated[-1]["feedback"] if evaluated else None,
            "history": state["history"], "last_error": state["last_error"],
            "preserved_answer": state["response"],
            "context_outdated": context_outdated(metadata),
        }

    @contextmanager
    def checkpoint(path, step=None):
        with SqliteSaver.from_conn_string(str(path / "checkpoints.sqlite")) as saver:
            graph = build_coaching_graph(step or (lambda state: {}), saver)
            config = {"configurable": {"thread_id": "browser-session"}}
            yield graph, config

    @router.get("/captures/{capture_uuid}/coaching")
    def list_sessions(capture_uuid: UUID):
        with preparation_errors():
            load_capture(database, capture_uuid)
            paths = list((root / str(capture_uuid)).glob("*/session.json"))
            paths.sort(key=lambda item: item.stat().st_mtime_ns, reverse=True)
            return [
                {"session_uuid": path.parent.name,
                 "created_at": metadata_for(path.parent)["created_at"]}
                for path in paths
            ]

    @router.post("/captures/{capture_uuid}/coaching")
    def start(capture_uuid: UUID, request: StartCoachingRequest):
        with preparation_errors():
            path = directory(capture_uuid, request.request_uuid)
            if (path / "session.json").exists():
                with session_lock(path), checkpoint(path) as (graph, config):
                    if metadata_for(path)["guide_uuid"] != str(request.guide_uuid):
                        raise ValueError("Session request already uses a different guide.")
                    return report(path, graph.get_state(config).values)
            if latest_guide(capture_uuid) != request.guide_uuid:
                raise ValueError("A newer guide exists. Reload preparation before starting.")
            manifest = load_current_guide_manifest(
                database, profile_path, preparation, capture_uuid, request.guide_uuid
            )
            try:
                path.mkdir(parents=True, exist_ok=False)
            except FileExistsError as error:
                raise ValueError("Session creation is running or incomplete. Reload first.") from error
            with session_lock(path), checkpoint(path) as (graph, config):
                initial = new_coaching_state(
                    [item["question"] for item in manifest["guide"]["practice_questions"]],
                    manifest["profile_snapshot"], state_revision(manifest),
                )
                graph.update_state(config, initial, as_node="coach")
                write_json(path / "session.json", {
                    "capture_uuid": str(capture_uuid),
                    "guide_uuid": str(request.guide_uuid),
                    "guide_sha256": state_revision(manifest),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "guide_snapshot": manifest,
                })
                return report(path, graph.get_state(config).values)

    @router.get("/captures/{capture_uuid}/coaching/{session_uuid}")
    def read(capture_uuid: UUID, session_uuid: UUID):
        with preparation_errors():
            path = directory(capture_uuid, session_uuid)
            metadata_for(path)
            with session_lock(path), checkpoint(path) as (graph, config):
                return report(path, graph.get_state(config).values)

    @router.post("/captures/{capture_uuid}/coaching/{session_uuid}/actions")
    def act(capture_uuid: UUID, session_uuid: UUID, request: CoachingActionRequest):
        with preparation_errors():
            path = directory(capture_uuid, session_uuid)
            metadata_for(path)
            with session_lock(path):
                receipt_path = path / "operations" / f"{request.request_uuid}.json"
                fingerprint = state_revision(request.model_dump(mode="json"))
                with checkpoint(path) as (graph, config):
                    state = graph.get_state(config).values
                    if receipt_path.exists():
                        receipt = json.loads(receipt_path.read_bytes())
                        if receipt["fingerprint"] != fingerprint:
                            raise ValueError("Request ID already has different coaching inputs.")
                        if receipt["status"] != "completed":
                            raise ValueError(
                                "The previous request was interrupted. Reload history "
                                "before explicitly submitting a new answer."
                            )
                        return report(path, state)
                    if state_revision(state) != request.expected_revision:
                        raise ValueError("Session changed in another tab. Reload before continuing.")
                    if request.action == "answer":
                        answer = request.answer.strip()
                        if not answer:
                            raise ValueError("Enter a practice answer first.")
                        if state["status"] != "active" or state["phase"] not in {"main", "followup"}:
                            raise ValueError("This session is not awaiting an answer.")
                        if state["request_count"] >= 4:
                            raise ValueError("Request limit reached. Skip this question.")
                        # Validate configuration before reserving the request budget.
                        evaluator = configured_step()
                    else:
                        if request.answer:
                            raise ValueError("Only answer actions may contain answer text.")
                        changes = apply_coaching_command(state, "/" + request.action)
                    receipt_path.parent.mkdir(exist_ok=True)
                    write_json(receipt_path, {"status": "started", "fingerprint": fingerprint})
                    if request.action != "answer":
                        graph.update_state(config, changes, as_node="coach")
                        result = graph.get_state(config).values
                    else:
                        # Persist budget BEFORE evaluation, including interrupted calls.
                        graph.update_state(config, {
                            "request_count": state["request_count"] + 1,
                            "response": answer,
                            "last_error": "Evaluation in progress or interrupted. Reload after it finishes.",
                        }, as_node="coach")
                        result = None
                if request.action == "answer":
                    def reserved_step(current):
                        # The core step increments its input counter; budget is already reserved.
                        evaluation_state = dict(current)
                        evaluation_state["request_count"] -= 1
                        return evaluator(evaluation_state)

                    with checkpoint(path, reserved_step) as (graph, config):
                        result = graph.invoke({}, config)
                write_json(receipt_path, {"status": "completed", "fingerprint": fingerprint})
                return report(path, result)

    return router
