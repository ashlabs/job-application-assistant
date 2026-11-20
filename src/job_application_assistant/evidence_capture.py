"""Read selected saved workflow outputs without making provider requests."""

import http.client
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from uuid import UUID


@dataclass(frozen=True)
class SavedResponse:
    status: int
    body: object


def local_reader(token: str):
    """Use only the fixed loopback API; redirects are never followed."""
    if not token.strip():
        raise ValueError("Set CAPTURE_API_TOKEN in the project's .env file.")

    def read(path: str) -> SavedResponse:
        connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=15)
        try:
            connection.request("GET", path, headers={"X-Capture-Token": token.strip()})
            response = connection.getresponse()
            raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise ValueError("The saved API response exceeds the evidence limit.")
            if response.status == 401:
                raise PermissionError("The API rejected the capture token.")
            if 300 <= response.status < 400:
                raise ValueError("The local API attempted a redirect; it was not followed.")
            return SavedResponse(response.status, json.loads(raw))
        finally:
            connection.close()
    return read


def collect_saved_evidence(capture_uuid: UUID, reader, session_uuid: UUID | None = None):
    """Record actual GET responses, including absent or outdated outputs."""
    capture_uuid = UUID(str(capture_uuid))
    base = f"/captures/{capture_uuid}"
    records = []

    def read(name, path):
        response = reader(path)
        encoded = json.dumps(response.body, sort_keys=True, ensure_ascii=False).encode("utf-8")
        records.append({
            "name": name, "method": "GET", "path": path,
            "status": response.status, "body": response.body,
            "body_sha256": sha256(encoded).hexdigest(),
        })
        return response

    capture = read("capture", base)
    if capture.status != 200:
        raise ValueError("The selected capture could not be read. Check its UUID and the API.")
    if not isinstance(capture.body, dict) or capture.body.get("capture_uuid") != str(capture_uuid):
        raise ValueError("The local API returned a different capture.")
    for name, suffix in [
        ("requirements", "/requirements"), ("match", "/profile-match"),
        ("resume", "/resumes/latest"), ("research", "/research/latest"),
        ("interview_guide", "/interview-guides/latest"),
    ]:
        read(name, base + suffix)
    sessions = read("practice_sessions", base + "/coaching")
    selected = session_uuid
    if selected is None and sessions.status == 200 and isinstance(sessions.body, list) and sessions.body:
        selected = UUID(sessions.body[0]["session_uuid"])
    if selected is not None:
        selected = UUID(str(selected))
        read("practice", base + f"/coaching/{selected}")
    return {
        "schema_version": 1,
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "capture_uuid": str(capture_uuid),
        "evidence_type": "saved_local_api_outputs",
        "provider_requests_made": 0,
        "limitations": [
            "These are saved application outputs, not a new provider run or a complete execution trace.",
            "Provider/model identity and original execution time are not inferred when absent.",
            "Null outputs and error statuses are recorded as observed, not replaced with sample successes.",
            "Selected content can include career and practice data; review before sharing.",
        ],
        "records": records,
    }


def write_evidence(bundle: dict, directory: Path) -> Path:
    """Create a new private bundle without overwriting earlier evidence."""
    directory.mkdir(parents=True, mode=0o700, exist_ok=False)
    target = directory / "saved-workflow-evidence.json"
    target.write_text(json.dumps(bundle, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    target.chmod(0o600)
    lines = [
        "# Saved workflow evidence", "",
        "These results were read from the selected local API capture. No AI requests were made.",
        "They are saved outputs, not a new provider run or a full execution trace.", "",
        "| Output | HTTP status | Saved body |", "| --- | --- | --- |",
    ]
    for item in bundle["records"]:
        body = "Not present" if item["body"] is None else "Recorded in JSON"
        lines.append(f"| {item['name']} | {item['status']} | {body} |")
    lines += ["", "Review the JSON and its actual missing/outdated results before describing this run in the report.", ""]
    summary = directory / "README.md"
    summary.write_text("\n".join(lines), encoding="utf-8")
    summary.chmod(0o600)
    return target
