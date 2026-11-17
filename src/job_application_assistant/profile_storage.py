"""Save reviewed career profiles on macOS and Linux."""

import fcntl
import os
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID

from job_application_assistant.profile_markdown import profile_from_markdown
from job_application_assistant.profile_review import (
    ProfileProposal,
    content_revision
)


class ProfileConflictError(ValueError):
    """The saved profile changed after a proposal was prepared."""


def _atomic_write(path: Path, content: str) -> None:
    """Replace a file only after its new content is fully written."""
    temporary_path = None

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(content)
            temporary.flush()
            os.fsync(temporary.fileno())

        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def save_approved_proposal(
    directory: Path,
    proposal: ProfileProposal,
    *,
    approved_proposal_uuid: UUID
) -> str:
    """Save the exact approved snapshot and return its revision."""
    if approved_proposal_uuid != proposal.proposal_uuid:
        raise PermissionError("Approval does not match this proposal.")

    # Revalidate before any profile files are changed.
    profile_from_markdown(proposal.proposed_markdown)
    new_revision = content_revision(proposal.proposed_markdown)

    directory.mkdir(parents=True, exist_ok=True)
    profile_path = directory / "career_profile.md"

    # Serialize saves from cooperating application processes.
    with (directory / ".profile.lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

        current = (
            profile_path.read_bytes().decode("utf-8")
            if profile_path.exists()
            else None
        )

        if current is not None:
            profile_from_markdown(current)

        # A retry of an already completed save is harmless.
        if current == proposal.proposed_markdown:
            return new_revision

        current_revision = (
            content_revision(current) if current is not None else None
        )

        if current_revision != proposal.base_revision:
            raise ProfileConflictError(
                "The profile changed during review. Prepare a new proposal."
            )

        if current is not None:
            history_directory = directory / "history"
            history_directory.mkdir(exist_ok=True)
            history_path = history_directory / f"{current_revision}.md"

            if history_path.exists():
                if history_path.read_bytes().decode("utf-8") != current:
                    raise ProfileConflictError(
                        "The historical version has unexpected content."
                    )
            else:
                _atomic_write(history_path, current)

        _atomic_write(profile_path, proposal.proposed_markdown)

    return new_revision
