"""Exercise persistent browser coaching with fake preparation and feedback."""

import json
from uuid import UUID, uuid4

import pytest
from fastapi import Header, HTTPException

from test_preparation_api import (
    HEADERS, capture_sources, generate, preparation_api,
)
from test_interview_coaching import FakeModel, make_feedback
from job_application_assistant.coaching_api import create_coaching_router
from job_application_assistant.interview_coaching import create_coaching_step
from job_application_assistant.preparation_api import write_json
from job_application_assistant.profile_markdown import profile_to_markdown


@pytest.fixture
def coaching_api(preparation_api, tmp_path):
    client, capture, calls, prep_root, profile, profile_path, requirements, database, _ = preparation_api
    research = capture_sources(client, capture).json()
    created = generate(client, capture, research)
    assert created.status_code == 200
    guide_id = created.json()["guide_uuid"]
    model = FakeModel(make_feedback("What did you personally do?"))
    core = create_coaching_step(model)
    behavior = {}

    def step(state):
        if behavior.get("crash"):
            raise RuntimeError("Simulated interrupted evaluator")
        return core(state)

    def require_token(x_capture_token: str | None = Header(default=None)):
        if x_capture_token != "preparation-test":
            raise HTTPException(401, "Invalid token.")

    root = tmp_path / "coaching"
    client.app.include_router(create_coaching_router(
        database, profile_path, require_token,
        preparation_root=prep_root, coaching_root=root, coaching_step=step,
    ))
    return {
        "client": client, "capture": capture, "guide_id": guide_id,
        "model": model, "root": root, "profile": profile,
        "profile_path": profile_path, "prep_root": prep_root,
        "behavior": behavior,
    }


def base(case):
    return f"/captures/{case['capture'].capture_uuid}/coaching"


def start(case, request_id=None):
    return case["client"].post(base(case), headers=HEADERS, json={
        "request_uuid": str(request_id or uuid4()),
        "guide_uuid": case["guide_id"], "confirmed": True,
    })


def act(case, state, action, answer="", request_id=None):
    return case["client"].post(
        base(case) + f"/{state['session_uuid']}/actions", headers=HEADERS,
        json={"request_uuid": str(request_id or uuid4()),
              "expected_revision": state["revision"],
              "action": action, "answer": answer},
    )


def test_start_list_answer_pause_reopen_resume_and_complete(coaching_api):
    case = coaching_api
    client = case["client"]
    original_profile = case["profile_path"].read_bytes()
    assert client.get(base(case), headers=HEADERS).json() == []
    created = start(case)
    assert created.status_code == 200
    state = created.json()
    assert state["question_number"] == 1
    assert state["status"] == "active"
    assert case["model"].calls == 0
    assert len(client.get(base(case), headers=HEADERS).json()) == 1

    main = act(case, state, "answer", "I coached engineers and led delivery reviews.")
    assert main.status_code == 200
    state = main.json()
    assert state["phase"] == "followup"
    state = act(case, state, "answer", "I assigned responsibilities.").json()
    assert state["phase"] == "review"
    assert state["followup_question"] is None
    assert state["request_count"] == 2
    state = act(case, state, "next").json()
    state = act(case, state, "pause").json()
    loaded = client.get(base(case) + f"/{state['session_uuid']}", headers=HEADERS).json()
    assert loaded == state
    assert loaded["status"] == "paused"
    assert loaded["question_number"] == 2
    assert case["model"].calls == 2
    state = act(case, loaded, "resume").json()
    for _ in range(4):
        response = act(case, state, "skip")
        assert response.status_code == 200
        state = response.json()
    assert state["status"] == "complete"
    assert state["question"] is None
    assert len([item for item in state["history"] if item["event"] == "evaluated"]) == 2
    assert case["profile_path"].read_bytes() == original_profile


def test_request_retries_do_not_repeat_creation_or_evaluation(coaching_api):
    case = coaching_api
    request_id = uuid4()
    first = start(case, request_id)
    second = start(case, request_id)
    assert first.json() == second.json()
    state = first.json()
    request_id = uuid4()
    first = act(case, state, "answer", "I coached engineers.", request_id)
    second = act(case, state, "answer", "I coached engineers.", request_id)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert case["model"].calls == 1


def test_stale_tab_is_rejected_before_another_model_request(coaching_api):
    case = coaching_api
    state = start(case).json()
    assert act(case, state, "answer", "I coached engineers.").status_code == 200
    response = act(case, state, "answer", "Another stale answer.")
    assert response.status_code == 409
    assert "another tab" in response.json()["detail"]
    assert case["model"].calls == 1


def test_paused_session_rejects_answers_without_ai(coaching_api):
    case = coaching_api
    state = act(case, start(case).json(), "pause").json()
    assert act(case, state, "answer", "My answer.").status_code == 409
    assert case["model"].calls == 0


def test_budget_survives_failures_and_blocks_fifth_request(coaching_api):
    from openai import OpenAIError
    case = coaching_api
    case["model"].feedback = OpenAIError("Provider unavailable")
    state = start(case).json()
    for count in range(1, 5):
        response = act(case, state, "answer", "My answer.")
        assert response.status_code == 200
        state = response.json()
        assert state["request_count"] == count
        assert state["last_error"]
        assert state["preserved_answer"] == "My answer."
    assert act(case, state, "answer", "Fifth answer.").status_code == 409
    assert case["model"].calls == 4
    state = act(case, state, "skip").json()
    assert state["question_number"] == 2
    assert state["request_count"] == 0


def test_interruption_preserves_reserved_budget_and_blocks_replay(coaching_api):
    case = coaching_api
    state = start(case).json()
    request_id = uuid4()
    case["behavior"]["crash"] = True
    with pytest.raises(RuntimeError, match="interrupted evaluator"):
        act(case, state, "answer", "My answer.", request_id)
    case["behavior"]["crash"] = False
    assert act(case, state, "answer", "My answer.", request_id).status_code == 409
    loaded = case["client"].get(base(case) + f"/{state['session_uuid']}", headers=HEADERS).json()
    assert loaded["request_count"] == 1
    assert loaded["preserved_answer"] == "My answer."
    result = act(case, loaded, "answer", "My explicit new attempt.")
    assert result.status_code == 200
    assert result.json()["request_count"] == 2
    assert case["model"].calls == 1


def test_retry_does_not_allow_second_followup(coaching_api):
    case = coaching_api
    state = start(case).json()
    state = act(case, state, "answer", "My main answer.").json()
    state = act(case, state, "answer", "My follow-up answer.").json()
    state = act(case, state, "retry").json()
    state = act(case, state, "answer", "My revised main answer.").json()
    assert state["phase"] == "review"
    assert state["followup_question"] is None
    assert state["request_count"] == 3


def test_changed_profile_flags_old_session_but_blocks_new_start(coaching_api):
    case = coaching_api
    state = start(case).json()
    case["profile"].education[0].completion_date = "2012"
    case["profile_path"].write_text(profile_to_markdown(case["profile"]), encoding="utf-8")
    loaded = case["client"].get(base(case) + f"/{state['session_uuid']}", headers=HEADERS)
    assert loaded.status_code == 200
    assert loaded.json()["context_outdated"]
    assert act(case, loaded.json(), "pause").status_code == 200
    assert start(case).status_code == 409
    assert case["model"].calls == 0


def test_multiple_sessions_remain_available(coaching_api):
    case = coaching_api
    first = start(case).json()
    second = start(case).json()
    sessions = case["client"].get(base(case), headers=HEADERS).json()
    assert {item["session_uuid"] for item in sessions} == {
        first["session_uuid"], second["session_uuid"]
    }
    assert case["client"].get(base(case) + f"/{first['session_uuid']}", headers=HEADERS).status_code == 200
    assert case["model"].calls == 0


@pytest.mark.parametrize("endpoint", ["list", "start", "read", "action"])
def test_all_coaching_routes_require_authentication(coaching_api, endpoint):
    case = coaching_api
    path = base(case)
    client = case["client"]
    if endpoint == "list":
        response = client.get(path)
    elif endpoint == "start":
        response = client.post(path, json={"request_uuid": str(uuid4()), "guide_uuid": case["guide_id"], "confirmed": True})
    elif endpoint == "read":
        response = client.get(path + f"/{uuid4()}")
    else:
        response = client.post(path + f"/{uuid4()}/actions", json={
            "request_uuid": str(uuid4()), "expected_revision": "a" * 64,
            "action": "answer", "answer": "My answer.",
        })
    assert response.status_code == 401
    assert not case["root"].exists()
    assert case["model"].calls == 0


def test_session_cannot_be_read_under_another_job(coaching_api):
    case = coaching_api
    state = start(case).json()
    path = f"/captures/{uuid4()}/coaching/{state['session_uuid']}"
    assert case["client"].get(path, headers=HEADERS).status_code == 404


def test_start_requires_explicit_confirmation(coaching_api):
    case = coaching_api
    response = case["client"].post(base(case), headers=HEADERS, json={
        "request_uuid": str(uuid4()), "guide_uuid": case["guide_id"], "confirmed": False,
    })
    assert response.status_code == 422
    assert not case["root"].exists()


def test_session_really_reopens_from_saved_checkpoints(coaching_api):
    case = coaching_api
    state = start(case).json()
    state = act(case, state, "answer", "I coached engineers.").json()
    state = act(case, state, "pause").json()
    # Each API request constructs a new graph and opens the on-disk saver.
    loaded = case["client"].get(base(case) + f"/{state['session_uuid']}", headers=HEADERS)
    assert loaded.json() == state
    assert case["model"].calls == 1


def test_running_operation_is_rejected_without_another_evaluation(coaching_api):
    from job_application_assistant.coaching_api import session_lock
    case = coaching_api
    state = start(case).json()
    path = case["root"] / str(case["capture"].capture_uuid) / state["session_uuid"]
    with session_lock(path):
        response = act(case, state, "answer", "My answer.")
    assert response.status_code == 409
    assert "operation is running" in response.json()["detail"]
    assert case["model"].calls == 0


def test_reusing_request_id_with_different_answer_is_rejected(coaching_api):
    case = coaching_api
    state = start(case).json()
    request_id = uuid4()
    assert act(case, state, "answer", "First answer.", request_id).status_code == 200
    response = act(case, state, "answer", "Different answer.", request_id)
    assert response.status_code == 409
    assert "different coaching inputs" in response.json()["detail"]
    assert case["model"].calls == 1
