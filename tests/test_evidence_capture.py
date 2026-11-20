"""Saved evidence is read-only, provenance-labelled, and failure-preserving."""

import json
from uuid import uuid4
import pytest

from test_profile_match_api import match_api, HEADERS
from job_application_assistant.evidence_capture import (
    SavedResponse, collect_saved_evidence, local_reader, write_evidence,
)


def test_saved_bundle_uses_only_reads_and_does_not_reassess(match_api, tmp_path):
    client, _, _, capture, calls, _ = match_api
    response = client.post(f"/captures/{capture.capture_uuid}/profile-match", headers=HEADERS)
    assert response.status_code == 200
    reads = []
    def reader(path):
        reads.append(path)
        response = client.get(path, headers=HEADERS)
        return SavedResponse(response.status_code, response.json())
    bundle = collect_saved_evidence(capture.capture_uuid, reader)
    assert bundle["provider_requests_made"] == 0
    assert len(calls) == 1
    assert bundle["evidence_type"] == "saved_local_api_outputs"
    assert all(item["method"] == "GET" for item in bundle["records"])
    match = next(item for item in bundle["records"] if item["name"] == "match")
    assert match["body"] == response.json()
    target = write_evidence(bundle, tmp_path / "evidence")
    assert json.loads(target.read_text()) == bundle
    assert "X-Capture-Token" not in target.read_text()
    assert HEADERS["X-Capture-Token"] not in target.read_text()
    with pytest.raises(FileExistsError):
        write_evidence(bundle, target.parent)


def test_absent_outputs_and_outdated_guide_are_not_replaced_with_successes():
    capture_uuid, session_uuid = uuid4(), uuid4()
    def reader(path):
        if path == f"/captures/{capture_uuid}":
            return SavedResponse(200, {"capture_uuid": str(capture_uuid)})
        if path.endswith("/interview-guides/latest"):
            return SavedResponse(409, {"detail": "The approved profile changed."})
        if path.endswith("/coaching"):
            return SavedResponse(200, [{"session_uuid": str(session_uuid)}])
        if path.endswith(str(session_uuid)):
            return SavedResponse(200, {"status": "paused", "context_outdated": True, "history": []})
        return SavedResponse(200, None)
    bundle = collect_saved_evidence(capture_uuid, reader)
    guide = next(item for item in bundle["records"] if item["name"] == "interview_guide")
    assert guide["status"] == 409
    assert "changed" in guide["body"]["detail"]
    assert next(item for item in bundle["records"] if item["name"] == "match")["body"] is None
    assert bundle["records"][-1]["body"]["context_outdated"] is True


@pytest.mark.parametrize("problem", ["missing", "different"])
def test_capture_identity_checked_before_reading_related_outputs(problem):
    calls = []
    def reader(path):
        calls.append(path)
        return SavedResponse(404, {}) if problem == "missing" else SavedResponse(200, {"capture_uuid": str(uuid4())})
    with pytest.raises(ValueError):
        collect_saved_evidence(uuid4(), reader)
    assert len(calls) == 1


def test_selected_session_is_not_silently_replaced_with_another():
    capture_uuid, selected, latest = uuid4(), uuid4(), uuid4()
    paths = []
    def reader(path):
        paths.append(path)
        if path == f"/captures/{capture_uuid}":
            return SavedResponse(200, {"capture_uuid": str(capture_uuid)})
        return SavedResponse(200, [{"session_uuid": str(latest)}]) if path.endswith("/coaching") else SavedResponse(200, None)
    collect_saved_evidence(capture_uuid, reader, selected)
    assert paths[-1].endswith(str(selected))


@pytest.mark.parametrize("status", [200, 302, 401])
def test_http_reader_uses_fixed_loopback_get_and_never_follows_redirects(monkeypatch, status):
    from job_application_assistant import evidence_capture
    calls = []
    class Connection:
        def __init__(self, host, port, timeout):
            assert (host, port) == ("127.0.0.1", 8000)
        def request(self, method, path, headers):
            calls.append((method, path))
            assert headers == {"X-Capture-Token": "secret-token"}
        def getresponse(self):
            return type("Response", (), {"status": status, "read": lambda self, limit: b"null"})()
        def close(self): calls.append("closed")
    monkeypatch.setattr(evidence_capture.http.client, "HTTPConnection", Connection)
    read = local_reader("secret-token")
    if status == 200:
        assert read("/captures/example").body is None
    else:
        with pytest.raises(ValueError if status == 302 else PermissionError):
            read("/captures/example")
    assert calls == [("GET", "/captures/example"), "closed"]


def test_freeze_helper_accepts_only_exact_portable_pins():
    import runpy
    from pathlib import Path
    helper = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/freeze_environment.py"))
    validate = helper["validated_pins"]
    assert validate("pydantic==2.14.4\nfastapi==0.165.0\n") == "fastapi==0.165.0\npydantic==2.14.4\n"
    for text in ("-e /home/example/project", "package @ file:///tmp/wheel", "package>=1", ""):
        with pytest.raises(ValueError): validate(text)


def test_cli_rejects_arbitrary_capture_paths():
    from job_application_assistant.system_cli import main
    with pytest.raises(SystemExit):
        main(["evidence", "--capture-uuid", "../../private"])


def test_server_entry_uses_existing_app_on_loopback(monkeypatch):
    import uvicorn
    from job_application_assistant import capture_api
    from job_application_assistant.system_cli import main
    marker = object()
    calls = []
    monkeypatch.setattr(capture_api, "create_app", lambda: marker)
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    main(["serve"])
    assert calls == [(marker, {"host": "127.0.0.1", "port": 8000})]


def test_cli_error_does_not_print_credentials_or_raw_exception(monkeypatch, capsys):
    import dotenv
    from job_application_assistant import evidence_capture
    from job_application_assistant.system_cli import main
    monkeypatch.setattr(dotenv, "dotenv_values", lambda path: {"CAPTURE_API_TOKEN": "secret-token"})
    def fail(token):
        raise PermissionError("secret-token from a sensitive exception")
    monkeypatch.setattr(evidence_capture, "local_reader", fail)
    with pytest.raises(SystemExit):
        main(["evidence", "--capture-uuid", str(uuid4())])
    output = capsys.readouterr()
    assert "secret-token" not in output.err
    assert "PermissionError" in output.err
