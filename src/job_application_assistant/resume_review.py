"""Review and approve exact, current resume drafts."""

import argparse
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from dotenv import dotenv_values

from job_application_assistant.job_requirements import JobRequirements
from job_application_assistant.job_requirements_storage import (
    load_requirements,
)
from job_application_assistant.models import CareerProfile
from job_application_assistant.profile_match_service import (
    load_saved_profile,
)
from job_application_assistant.profile_match_validation import (
    profile_revision,
    requirements_revision,
)
from job_application_assistant.resume_draft import (
    ROOT,
    ResumeSelection,
    render_resume,
)


def review_draft(directory, profile, requirements):
    """Validate sources and rendering; identify the exact reviewed files."""
    directory = Path(directory)
    resume_bytes = (directory / "resume.txt").read_bytes()
    evidence_bytes = (directory / "evidence.json").read_bytes()
    text = resume_bytes.decode("utf-8")
    manifest = json.loads(evidence_bytes)

    if manifest["status"] != "draft_requires_review":
        raise ValueError("Unexpected draft status.")
    if manifest["capture_uuid"] != str(requirements.capture_uuid):
        raise ValueError("The draft belongs to a different job.")

    snapshot = CareerProfile.model_validate(
        manifest["approved_source_snapshot"]
    )
    job_snapshot = JobRequirements.model_validate(
        manifest["requirements_snapshot"]
    )
    if (
        manifest["profile_sha256"] != profile_revision(snapshot)
        or manifest["profile_sha256"] != profile_revision(profile)
    ):
        raise ValueError("The profile changed. Generate a new draft.")
    if (
        manifest["requirements_sha256"]
        != requirements_revision(job_snapshot)
        or manifest["requirements_sha256"]
        != requirements_revision(requirements)
    ):
        raise ValueError("Job requirements changed. Generate a new draft.")

    selection = ResumeSelection.model_validate(manifest["selection"])
    name = text.splitlines()[0] if text.splitlines() else ""
    if render_resume(profile, selection, name) != text:
        raise ValueError(
            "Resume text differs from its evidence-backed rendering. "
            "Correct the approved profile and generate a new draft."
        )

    hashes = {
        "resume_sha256": sha256(resume_bytes).hexdigest(),
        "evidence_sha256": sha256(evidence_bytes).hexdigest(),
    }
    token = sha256(
        json.dumps(hashes, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {
        "text": text,
        "review_token": token,
        **hashes,
    }


def approve_draft(directory, profile, requirements, reviewed_token):
    """Approve only files matching the token displayed during review."""
    review = review_draft(directory, profile, requirements)
    if reviewed_token != review["review_token"]:
        raise ValueError("The reviewed files changed. Review again.")

    receipt = {
        "status": "approved",
        "review_token": review["review_token"],
        "resume_sha256": review["resume_sha256"],
        "evidence_sha256": review["evidence_sha256"],
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }
    path = Path(directory) / "approval.json"
    content = json.dumps(receipt, indent=2) + "\n"

    # Exclusive creation prevents silently replacing an approval receipt.
    with path.open("x", encoding="utf-8") as output:
        output.write(content)
    return receipt


def verify_approval(directory, profile, requirements):
    """Return current approved text for a future export operation."""
    review = review_draft(directory, profile, requirements)
    path = Path(directory) / "approval.json"
    if not path.exists():
        raise ValueError("This resume has not been approved.")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("status") != "approved":
        raise ValueError("Invalid approval status.")
    for key in ("review_token", "resume_sha256", "evidence_sha256"):
        if receipt.get(key) != review[key]:
            raise ValueError("Approval no longer matches this draft.")
    return review["text"]


def main():
    """Display the draft, then approve or verify it locally."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    def current_inputs():
        settings = dotenv_values(ROOT / ".env")
        configured = (
            settings.get("CAREER_PROFILE_PATH")
            or "data/private/profile/career_profile.md"
        ).strip()
        profile = load_saved_profile((ROOT / configured).resolve())
        manifest = json.loads(
            (args.directory / "evidence.json").read_text(
                encoding="utf-8"
            )
        )
        requirements = load_requirements(
            ROOT / "data/private/job_captures.sqlite",
            UUID(manifest["capture_uuid"]),
        )
        if requirements is None:
            raise ValueError("Saved job requirements are unavailable.")
        return profile, requirements

    profile, requirements = current_inputs()
    if args.check:
        verify_approval(args.directory, profile, requirements)
        print("Approval is valid for the current draft and sources.")
        return

    review = review_draft(args.directory, profile, requirements)
    print(review["text"])
    print(f"Review token: {review['review_token']}")
    entered = input(
        "Review the resume and evidence.json. "
        "To approve, enter APPROVE followed by the full review token: "
    ).strip()
    if entered != f"APPROVE {review['review_token']}":
        print("Not approved. Draft preserved.")
        return

    # Reload sources after the user finishes reviewing.
    profile, requirements = current_inputs()
    approve_draft(
        args.directory, profile, requirements, review["review_token"]
    )
    print("Exact draft approved. No documents exported or submitted.")


if __name__ == "__main__":
    main()