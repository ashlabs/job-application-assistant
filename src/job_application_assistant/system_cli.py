"""Launch the local application or record selected saved workflow evidence."""

import argparse
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


def main(argv=None):
    parser = argparse.ArgumentParser(description="Job Application and Interview Assistant capstone")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("serve", help="Start the local API on 127.0.0.1:8000")
    evidence = commands.add_parser("evidence", help="Read selected saved outputs; makes no AI requests")
    evidence.add_argument("--capture-uuid", type=UUID, required=True)
    evidence.add_argument("--session-uuid", type=UUID)
    evidence.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn
        from job_application_assistant.capture_api import create_app
        uvicorn.run(create_app(), host="127.0.0.1", port=8000)
        return
    from dotenv import dotenv_values
    from job_application_assistant.evidence_capture import (
        collect_saved_evidence, local_reader, write_evidence,
    )
    root = Path(__file__).resolve().parents[2]
    token = dotenv_values(root / ".env").get("CAPTURE_API_TOKEN") or ""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    directory = args.output_dir or root / "data/private/evidence" / f"{stamp}-{args.capture_uuid}"
    try:
        bundle = collect_saved_evidence(args.capture_uuid, local_reader(token), args.session_uuid)
        target = write_evidence(bundle, directory)
    except (OSError, ValueError, KeyError, TypeError) as error:
        # Never print request headers, tokens, or raw server responses.
        parser.exit(1, f"Evidence capture failed ({type(error).__name__}). Check the API, token, UUID, and output directory.\n")
    print(f"Saved evidence: {target}")
    print("No AI request was made. Review the recorded statuses and content before sharing.")


if __name__ == "__main__":
    main()
