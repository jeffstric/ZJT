import json
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest

from script_writer_core.agents.ask_user_mixin import AskUserMixin
from services.user_module_agent_service import (
    UserModuleAgentAnswerError,
    UserModuleAgentService,
    UserModuleAgentTaskNotFoundError,
)
from services.user_module_ask_user_adapter import (
    LIMIT_QUESTION_ID,
    BackgroundAskUserAdapter,
    assemble_user_input,
    normalize_options,
    question_resolution,
)
from tests.module_runtime.test_user_module_agent_service import FakeGenerationService, _wait_terminal


TASK_ID = "22222222-2222-2222-2222-222222222222"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _service(tmp_path, **kwargs):
    defaults = {
        "module_root": tmp_path / "user-modules",
        "generation_service": FakeGenerationService(),
        "question_timeout_seconds": 0.4,
        "question_poll_interval_seconds": 0.05,
        "max_questions": 3,
        "heartbeat_interval_seconds": 0.1,
        "stale_timeout_seconds": 0.4,
    }
    defaults.update(kwargs)
    return UserModuleAgentService(**defaults)


def _seed_running_task(service, *, created_by="7", extra=None):
    now = _now()
    state = {
        "task_id": TASK_ID,
        "generation_id": "11111111-1111-1111-1111-111111111111",
        "created_by": created_by,
        "status": "running",
        "messages": [{"id": 1, "type": "running", "content": "go", "created_at": now}],
        "next_message_id": 2,
        "created_at": now,
        "updated_at": now,
        "heartbeat_at": now,
    }
    if extra:
        state.update(extra)
    service._task_path(TASK_ID).write_text(json.dumps(state), encoding="utf-8")
    return TASK_ID


def test_normalize_options_and_user_input_assembly():
    assert normalize_options(["是", "否", "是"]) == [
        {"value": "是", "label": "是"},
        {"value": "否", "label": "否"},
    ]
    assert assemble_user_input(
        options=[{"value": "yes", "label": "接入图片编辑"}],
        selected="yes",
        free_text="文档第三节",
    ) == "接入图片编辑\n文档第三节"


def test_adapter_question_roundtrip(tmp_path):
    service = _service(tmp_path)
    _seed_running_task(service)
    adapter = BackgroundAskUserAdapter(service, TASK_ID)

    verification = adapter.create_verification(
        TASK_ID,
        "ask_user",
        "能力覆盖确认",
        "是否同时接入图片编辑？",
        options=["是", "否"],
    )
    assert verification.verification_id.startswith("q_")
    state = service._read_task_sync(TASK_ID)
    question = next(item for item in state["messages"] if item["type"] == "question")
    assert question["allow_free_text"] is True
    assert question["options"][0]["value"] == "是"

    result_box = {}

    def wait():
        result_box["result"] = adapter.wait_for_verification(verification, timeout=300)

    waiter = threading.Thread(target=wait)
    waiter.start()
    time.sleep(0.08)
    payload = service._submit_answer_sync(
        TASK_ID,
        requester_id="7",
        question_id=verification.verification_id,
        selected="是",
        free_text="编辑接口见文档第三节",
    )
    waiter.join(timeout=2)
    assert not waiter.is_alive()
    assert payload["selected"] == "是"
    result = result_box["result"]
    assert result["success"] is True
    assert result["status"] == "approved"
    assert "是" in result["user_input"]
    assert "编辑接口见文档第三节" in result["user_input"]


def test_adapter_timeout_returns_mixin_timeout_shape(tmp_path):
    service = _service(tmp_path, question_timeout_seconds=0.15, question_poll_interval_seconds=0.04)
    _seed_running_task(service)
    adapter = BackgroundAskUserAdapter(service, TASK_ID)
    verification = adapter.create_verification(
        TASK_ID, "ask_user", "超时测试", "请尽快回答", options=["好"]
    )
    result = adapter.wait_for_verification(verification, timeout=300)
    assert result == {"success": False, "status": "timeout", "error": "验证超时"}
    state = service._read_task_sync(TASK_ID)
    assert any(item.get("type") == "question_timeout" for item in state["messages"])
    status, _event = question_resolution(state["messages"], verification.verification_id)
    assert status == "timeout"


def test_adapter_rejects_fourth_question(tmp_path):
    service = _service(tmp_path, max_questions=3)
    _seed_running_task(service)
    adapter = BackgroundAskUserAdapter(service, TASK_ID)
    for index in range(3):
        verification = adapter.create_verification(
            TASK_ID, "ask_user", f"问{index}", f"内容{index}", options=["ok"]
        )
        assert verification.verification_id != LIMIT_QUESTION_ID
    limited = adapter.create_verification(
        TASK_ID, "ask_user", "第四问", "不应发出", options=["ok"]
    )
    assert limited.verification_id == LIMIT_QUESTION_ID
    result = adapter.wait_for_verification(limited, timeout=300)
    assert result["success"] is False
    assert result["status"] == "limit"
    assert "上限" in result["error"]
    state = service._read_task_sync(TASK_ID)
    assert sum(1 for item in state["messages"] if item.get("type") == "question") == 3


def test_adapter_respects_task_max_questions_for_comfyui(tmp_path):
    service = _service(tmp_path, max_questions=3)
    _seed_running_task(service, extra={"max_questions": 15})
    adapter = BackgroundAskUserAdapter(service, TASK_ID)
    for index in range(4):
        verification = adapter.create_verification(
            TASK_ID, "ask_user", f"问{index}", f"内容{index}", options=["ok"]
        )
        assert verification.verification_id != LIMIT_QUESTION_ID
    state = service._read_task_sync(TASK_ID)
    assert sum(1 for item in state["messages"] if item.get("type") == "question") == 4


def test_submit_answer_rejects_stale_and_duplicate(tmp_path):
    service = _service(tmp_path, stale_timeout_seconds=0.2)
    stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    _seed_running_task(service, extra={"heartbeat_at": stale, "updated_at": stale, "created_at": stale})
    adapter = BackgroundAskUserAdapter(service, TASK_ID)
    # 先用新鲜心跳发出问题，再把心跳打成过期。
    service._heartbeat_task_sync(TASK_ID)
    verification = adapter.create_verification(
        TASK_ID, "ask_user", "过期", "请回答", options=["是"]
    )
    path = service._task_path(TASK_ID)
    state = json.loads(path.read_text(encoding="utf-8"))
    state["heartbeat_at"] = stale
    state["updated_at"] = stale
    path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(UserModuleAgentAnswerError) as interrupted:
        service._submit_answer_sync(
            TASK_ID,
            requester_id="7",
            question_id=verification.verification_id,
            selected="是",
            free_text=None,
        )
    assert interrupted.value.code == "agent_task_interrupted"
    assert interrupted.value.status_code == 409

    fresh = _service(tmp_path / "fresh")
    _seed_running_task(fresh)
    adapter = BackgroundAskUserAdapter(fresh, TASK_ID)
    verification = adapter.create_verification(
        TASK_ID, "ask_user", "重复", "请回答", options=["是"]
    )
    fresh._submit_answer_sync(
        TASK_ID,
        requester_id="7",
        question_id=verification.verification_id,
        selected="是",
        free_text=None,
    )
    with pytest.raises(UserModuleAgentAnswerError) as duplicate:
        fresh._submit_answer_sync(
            TASK_ID,
            requester_id="7",
            question_id=verification.verification_id,
            selected="是",
            free_text=None,
        )
    assert duplicate.value.code == "question_already_answered"

    with pytest.raises(UserModuleAgentTaskNotFoundError):
        fresh._submit_answer_sync(
            TASK_ID,
            requester_id="8",
            question_id=verification.verification_id,
            selected="是",
            free_text=None,
        )


def test_concurrent_answers_only_persist_one(tmp_path):
    service = _service(tmp_path)
    _seed_running_task(service)
    adapter = BackgroundAskUserAdapter(service, TASK_ID)
    verification = adapter.create_verification(
        TASK_ID, "ask_user", "竞态", "请选择", options=["A", "B"]
    )
    errors = []

    def answer(choice):
        try:
            service._submit_answer_sync(
                TASK_ID,
                requester_id="7",
                question_id=verification.verification_id,
                selected=choice,
                free_text=None,
            )
        except UserModuleAgentAnswerError as exc:
            errors.append(exc.code)

    first = threading.Thread(target=answer, args=("A",))
    second = threading.Thread(target=answer, args=("B",))
    first.start()
    second.start()
    first.join()
    second.join()
    state = service._read_task_sync(TASK_ID)
    answers = [item for item in state["messages"] if item.get("type") == "answer"]
    assert len(answers) == 1
    assert errors == ["question_already_answered"] or answers[0]["selected"] in {"A", "B"}


def test_mixin_uses_adapter_instead_of_unavailable_fallback(tmp_path):
    service = _service(tmp_path)
    _seed_running_task(service)
    adapter = BackgroundAskUserAdapter(service, TASK_ID)

    class _Agent(AskUserMixin):
        agent_id = "expert_generate-user-api-module"

        def __init__(self):
            self.task_manager = adapter
            self.task_id = TASK_ID
            self._ask_fail_count = 0

    agent = _Agent()
    box = {}

    def ask():
        box["result"] = agent._handle_ask_user(
            {"question": "是否接入图片编辑能力？", "options": ["是", "否"]}
        )

    worker = threading.Thread(target=ask)
    worker.start()
    deadline = time.time() + 2
    question_id = None
    while time.time() < deadline:
        state = service._read_task_sync(TASK_ID)
        question = next((item for item in state["messages"] if item.get("type") == "question"), None)
        if question:
            question_id = question["question_id"]
            break
        time.sleep(0.02)
    assert question_id
    service._submit_answer_sync(
        TASK_ID,
        requester_id="7",
        question_id=question_id,
        selected="是",
        free_text=None,
    )
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert box["result"].get("success") is True
    assert box["result"].get("user_input") == "是"


def test_wall_clock_pauses_during_question_wait(tmp_path, monkeypatch):
    generation_service = FakeGenerationService()
    service = UserModuleAgentService(
        module_root=tmp_path / "user-modules",
        generation_service=generation_service,
        heartbeat_interval_seconds=0.05,
        stale_timeout_seconds=0.12,
        wall_clock_timeout_seconds=0.25,
        question_timeout_seconds=1.5,
        question_poll_interval_seconds=0.05,
    )

    def execute(*, state, auth_token):
        del auth_token
        adapter = BackgroundAskUserAdapter(service, state["task_id"])
        verification = adapter.create_verification(
            state["task_id"],
            "ask_user",
            "墙钟",
            "等待管理员",
            options=["继续"],
        )
        result = adapter.wait_for_verification(verification, timeout=300)
        assert result["success"] is True
        generation_service.states[state["generation_id"]]["status"] = "validated"
        generation_service.states[state["generation_id"]]["validation"] = {"ok": True}
        return {"success": True, "result": "answered"}

    monkeypatch.setattr(service, "_execute_expert", execute)
    created = None

    async def scenario():
        nonlocal created
        created = await service.create_task(
            module_id="vendor.demo",
            requirement="实现一个异步图片生成接口",
            created_by="7",
            auth_token="secret-admin-token",
            model="demo-model",
            model_id=12,
            vendor_id=3,
        )
        deadline = time.time() + 2
        question_id = None
        while time.time() < deadline:
            state = service._read_task_sync(created["task_id"])
            question = next((item for item in state["messages"] if item.get("type") == "question"), None)
            if question:
                question_id = question["question_id"]
                break
            time.sleep(0.02)
        assert question_id
        time.sleep(0.5)
        service._submit_answer_sync(
            created["task_id"],
            requester_id="7",
            question_id=question_id,
            selected="继续",
            free_text=None,
        )
        return await _wait_terminal(service, created["task_id"])

    import asyncio

    terminal = asyncio.run(scenario())
    assert terminal["status"] == "completed"
    assert terminal.get("error_code") != "agent_task_wall_clock_timeout"


def test_adapter_push_message_records_tool_call(tmp_path):
    service = _service(tmp_path)
    _seed_running_task(service)
    adapter = BackgroundAskUserAdapter(service, TASK_ID)
    adapter.push_message(
        TASK_ID,
        "tool_call",
        {"tool_names": ["user_module_generation_write"], "count": 1},
    )
    state = json.loads(service._task_path(TASK_ID).read_text(encoding="utf-8"))
    events = [item for item in state["messages"] if item.get("type") == "tool_call"]
    assert len(events) == 1
    assert "user_module_generation_write" in events[0]["content"]


def test_adapter_power_confirm_is_noop(tmp_path):
    service = _service(tmp_path)
    adapter = BackgroundAskUserAdapter(service, TASK_ID)
    assert adapter.get_power_confirm_state("session") == {"skip": True, "approved_ceiling": 0}
    adapter.set_power_confirm_skip("session", True)
