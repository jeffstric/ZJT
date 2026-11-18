import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone

import pytest

from services.user_module_agent_service import (
    UserModuleAgentBusyError,
    UserModuleAgentService,
    UserModuleAgentTaskCancelledError,
    UserModuleAgentTaskNotFoundError,
    load_comfyui_workflow_text,
)


def test_load_comfyui_workflow_text_from_path_and_json(tmp_path):
    path = tmp_path / "wf.json"
    path.write_text('{"78": {"class_type": "LoadImage", "inputs": {"image": "a.png"}}}', encoding="utf-8")
    from_path = load_comfyui_workflow_text(workflow_path=str(path))
    assert "LoadImage" in from_path
    from_json = load_comfyui_workflow_text(workflow_json='{"3": {"class_type": "KSampler"}}')
    assert "KSampler" in from_json
    with pytest.raises(ValueError, match="普通文件"):
        load_comfyui_workflow_text(workflow_path=str(tmp_path))


class FakeGenerationService:
    def __init__(self):
        self.created = []
        self.states = {}
        self.files = {}

    async def create(self, **kwargs):
        self.created.append(kwargs)
        state = {
            "generation_id": "11111111-1111-1111-1111-111111111111",
            "module_id": kwargs["module_id"],
            "status": "draft",
        }
        self.states[state["generation_id"]] = state
        return state

    async def get(self, generation_id):
        return self.states[generation_id]

    async def list_files(self, generation_id):
        files = self.files.get(generation_id) or {}
        if files:
            return [{"path": path, "size": len(content.encode("utf-8"))} for path, content in files.items()]
        return [{"path": "manifest.json", "size": 2}]

    async def write_file(self, generation_id, relative_path, content):
        self.files.setdefault(generation_id, {})[relative_path] = content
        return {"path": relative_path, "size": len(content.encode("utf-8"))}


async def _wait_terminal(service, task_id):
    for _ in range(100):
        state = await asyncio.to_thread(service._read_task_sync, task_id)
        if state["status"] in {"completed", "failed"}:
            return state
        await asyncio.sleep(0.01)
    raise AssertionError("agent task did not finish")


def test_create_task_comfyui_writes_vendor_files(tmp_path, monkeypatch):
    async def scenario():
        generation_service = FakeGenerationService()
        service = UserModuleAgentService(
            module_root=tmp_path / "user-modules",
            generation_service=generation_service,
        )

        def fake_execute(*, state, auth_token):
            del auth_token
            generation_service.states[state["generation_id"]]["status"] = "validated"
            generation_service.states[state["generation_id"]]["validation"] = {"ok": True}
            assert state["connector"] == "local_comfyui"
            assert state["max_questions"] == 15
            return {"success": True, "result": "ready"}

        monkeypatch.setattr(service, "_execute_expert", fake_execute)
        created = await service.create_task(
            module_id="local.qwen-edit",
            requirement="",
            created_by="7",
            auth_token="token",
            model="demo-model",
            model_id=12,
            vendor_id=3,
            connector="local_comfyui",
            comfyui_base_url="http://192.168.10.187:8188/",
            workflow_json='{"78": {"class_type": "LoadImage", "inputs": {"image": "a.png"}}}',
        )
        terminal = await _wait_terminal(service, created["task_id"])
        assert terminal["status"] == "completed"
        assert created["max_questions"] == 15
        files = generation_service.files[created["generation_id"]]
        assert "vendor/workflow.json" in files
        assert "192.168.10.187:8188" in files["vendor/comfyui.json"]
        assert "LoadImage" in files["vendor/workflow.json"]

    asyncio.run(scenario())


def test_agent_task_precreates_generation_and_never_persists_token(tmp_path, monkeypatch):
    async def scenario():
        generation_service = FakeGenerationService()
        service = UserModuleAgentService(
            module_root=tmp_path / "user-modules",
            generation_service=generation_service,
        )

        seen = {}

        def fake_execute(*, state, auth_token):
            seen["state"] = state
            seen["auth_token"] = auth_token
            generation_service.states[state["generation_id"]]["status"] = "validated"
            generation_service.states[state["generation_id"]]["validation"] = {"ok": True}
            return {"success": True, "result": "ready for review"}

        monkeypatch.setattr(service, "_execute_expert", fake_execute)
        created = await service.create_task(
            module_id="vendor.demo",
            requirement="实现一个异步图片生成接口",
            created_by="7",
            auth_token="secret-admin-token",
            model="demo-model",
            model_id=12,
            vendor_id=3,
        )
        terminal = await _wait_terminal(service, created["task_id"])

        assert terminal["status"] == "completed"
        assert terminal["generation_status"] == "validated"
        # 默认 HTTP connector 提问上限为 15，与本地 ComfyUI 统一（unified_config.agent_task_max_questions）。
        assert created["max_questions"] == 15
        assert seen["state"]["generation_id"] == created["generation_id"]
        assert seen["auth_token"] == "secret-admin-token"
        assert generation_service.created == [{
            "module_id": "vendor.demo",
            "requirement": "实现一个异步图片生成接口",
            "created_by": "7",
            "review_model": "demo-model",
            "review_model_id": 12,
            "review_vendor_id": 3,
        }]

        persisted = json.loads(service._task_path(created["task_id"]).read_text(encoding="utf-8"))
        assert "auth_token" not in persisted
        assert "secret-admin-token" not in json.dumps(persisted, ensure_ascii=False)

        loaded = await service.get_task(created["task_id"], requester_id="7")
        assert loaded["generation"]["status"] == "validated"
        assert loaded["files"][0]["path"] == "manifest.json"
        assert [message["type"] for message in loaded["messages"]] == [
            "queued",
            "running",
            "completed",
        ]
        incremental = await service.get_task(
            created["task_id"], requester_id="7", after_id=2
        )
        assert [message["type"] for message in incremental["messages"]] == ["completed"]
        with pytest.raises(UserModuleAgentTaskNotFoundError):
            await service.get_task(created["task_id"], requester_id="8")

    asyncio.run(scenario())


def test_agent_task_failure_is_persisted_without_raising_to_creator(tmp_path, monkeypatch):
    async def scenario():
        service = UserModuleAgentService(
            module_root=tmp_path / "user-modules",
            generation_service=FakeGenerationService(),
        )

        def fail_execute(**_kwargs):
            raise RuntimeError("LLM failed")

        monkeypatch.setattr(service, "_execute_expert", fail_execute)
        created = await service.create_task(
            module_id="vendor.failed",
            requirement="实现一个异步视频生成接口",
            created_by="9",
            auth_token="transient-token",
            model="demo-model",
            model_id=12,
            vendor_id=3,
        )
        terminal = await _wait_terminal(service, created["task_id"])
        assert terminal["status"] == "failed"
        assert terminal["error"] == "LLM failed"

    asyncio.run(scenario())


def test_agent_task_fails_when_expert_skips_validation(tmp_path, monkeypatch):
    async def scenario():
        service = UserModuleAgentService(
            module_root=tmp_path / "user-modules",
            generation_service=FakeGenerationService(),
        )
        monkeypatch.setattr(
            service,
            "_execute_expert",
            lambda **_kwargs: {"success": True, "result": "claimed complete"},
        )
        created = await service.create_task(
            module_id="vendor.unvalidated",
            requirement="实现一个异步音频生成接口",
            created_by="9",
            auth_token="transient-token",
            model="demo-model",
            model_id=12,
            vendor_id=3,
        )
        terminal = await _wait_terminal(service, created["task_id"])
        assert terminal["status"] == "failed"
        assert "未完成模块校验" in terminal["error"]

    asyncio.run(scenario())


def test_agent_task_concurrency_limit_is_checked_before_generation(tmp_path, monkeypatch):
    async def scenario():
        generation_service = FakeGenerationService()
        service = UserModuleAgentService(
            module_root=tmp_path / "user-modules",
            generation_service=generation_service,
            max_concurrency=1,
        )
        release = asyncio.Event()

        def blocked_execute(**_kwargs):
            while not release.is_set():
                import time

                time.sleep(0.01)
            return {"success": True, "result": "done"}

        monkeypatch.setattr(service, "_execute_expert", blocked_execute)
        first = await service.create_task(
            module_id="vendor.first",
            requirement="实现第一个异步图片生成接口",
            created_by="7",
            auth_token="token-one",
            model="demo-model",
            model_id=12,
            vendor_id=3,
        )
        with pytest.raises(UserModuleAgentBusyError):
            await service.create_task(
                module_id="vendor.second",
                requirement="实现第二个异步图片生成接口",
                created_by="7",
                auth_token="token-two",
                model="demo-model",
                model_id=12,
                vendor_id=3,
            )
        assert len(generation_service.created) == 1
        release.set()
        await _wait_terminal(service, first["task_id"])

    asyncio.run(scenario())


def test_agent_task_concurrency_limit_is_shared_between_workers(tmp_path):
    first = UserModuleAgentService(
        module_root=tmp_path / "user-modules",
        generation_service=FakeGenerationService(),
        max_concurrency=1,
    )
    second = UserModuleAgentService(
        module_root=tmp_path / "user-modules",
        generation_service=FakeGenerationService(),
        max_concurrency=1,
    )
    lock = first._acquire_execution_slot()
    try:
        with pytest.raises(UserModuleAgentBusyError):
            second._acquire_execution_slot()
    finally:
        first._release_execution_slot(lock)


def test_stale_running_task_is_marked_interrupted_on_read(tmp_path):
    async def scenario():
        generation_service = FakeGenerationService()
        service = UserModuleAgentService(
            module_root=tmp_path / "user-modules",
            generation_service=generation_service,
            heartbeat_interval_seconds=0.1,
            stale_timeout_seconds=0.2,
        )
        task_id = "22222222-2222-2222-2222-222222222222"
        generation_id = "11111111-1111-1111-1111-111111111111"
        generation_service.states[generation_id] = {
            "generation_id": generation_id,
            "module_id": "vendor.interrupted",
            "status": "draft",
        }
        stale = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        service._task_path(task_id).write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "generation_id": generation_id,
                    "created_by": "7",
                    "status": "running",
                    "created_at": stale,
                    "updated_at": stale,
                    "heartbeat_at": stale,
                }
            ),
            encoding="utf-8",
        )

        state = await service.get_task(task_id, requester_id="7")
        assert state["status"] == "failed"
        assert state["error_code"] == "agent_task_interrupted"
        assert state["interrupted_at"]

    asyncio.run(scenario())


def test_agent_task_wall_clock_timeout_marks_failed(tmp_path, monkeypatch):
    """_execute_expert 长时间阻塞（如 LLM hang）时，挂钟超时应强制标记 failed（M4）。"""
    import time

    async def scenario():
        generation_service = FakeGenerationService()
        service = UserModuleAgentService(
            module_root=tmp_path / "user-modules",
            generation_service=generation_service,
            heartbeat_interval_seconds=0.1,
            stale_timeout_seconds=0.2,
            wall_clock_timeout_seconds=0.5,
        )

        def slow_execute(*, state, auth_token):
            time.sleep(1.5)  # 模拟 LLM hang，远超 0.5s 挂钟超时
            return {"success": True, "result": "不应到达此处"}

        monkeypatch.setattr(service, "_execute_expert", slow_execute)
        created = await service.create_task(
            module_id="vendor.demo",
            requirement="测试挂钟超时",
            created_by="7",
            auth_token="secret-admin-token",
            model="demo-model",
            model_id=12,
            vendor_id=3,
        )
        terminal = await _wait_terminal(service, created["task_id"])

        assert terminal["status"] == "failed"
        assert terminal["error_code"] == "agent_task_wall_clock_timeout"

    asyncio.run(scenario())


def test_grantable_secret_prompt_lists_catalog_without_values():
    """HTTP 供应商任务注入密钥清单：含规范名、配置键与描述，绝不包含密钥值。"""
    prompt = UserModuleAgentService._grantable_secret_prompt()

    assert "RUNNINGHUB_API_KEY" in prompt
    assert "runninghub.api_key" in prompt
    assert "HUIMENGI_API_KEY" in prompt
    assert "静态校验会拒绝清单外的名称" in prompt
    assert "ctx.secrets" in prompt
    # 目录带后台描述，可区分同族编号槽位
    assert "API 聚合站站点3 API Key" in prompt
    assert "API_AGGREGATOR_SITE_3_API_KEY" in prompt
    # 编号/共用槽位必须 ask_user 向管理员确认，禁止猜测
    assert "必须用 ask_user 请管理员确认" in prompt
    assert "禁止按编号顺序" in prompt


def test_list_tasks_returns_summaries_newest_first(tmp_path):
    """list_tasks 只返回当前管理员的任务摘要，按更新时间倒序。"""
    import asyncio

    service = UserModuleAgentService(
        module_root=tmp_path / "user-modules",
        generation_service=FakeGenerationService(),
    )
    task_root = service.task_root
    task_root.mkdir(parents=True, exist_ok=True)
    import os

    for index, (task_id, owner, updated) in enumerate(
        [
            ("11111111-1111-1111-1111-111111111111", "7", "2026-08-25T10:00:00"),
            ("22222222-2222-2222-2222-222222222222", "7", "2026-08-25T12:00:00"),
            ("33333333-3333-3333-3333-333333333333", "8", "2026-08-25T13:00:00"),
        ]
    ):
        task_file = task_root / f"{task_id}.json"
        task_file.write_text(
            json.dumps(
                {
                    "task_id": task_id,
                    "module_id": f"demo.module{index}",
                    "status": "completed",
                    "generation_id": f"gen-{index}",
                    "created_by": owner,
                    "messages": [{"id": 1, "type": "message", "content": "x" * 100}],
                    "created_at": "2026-08-25T09:00:00",
                    "updated_at": updated,
                }
            ),
            encoding="utf-8",
        )
        # 显式固定 mtime，避免连续写入时同秒时间戳导致排序不稳定
        os.utime(task_file, (2000000000 + index, 2000000000 + index))

    result = asyncio.run(service.list_tasks(limit=10, requester_id="7"))

    assert [item["task_id"] for item in result] == [
        "22222222-2222-2222-2222-222222222222",
        "11111111-1111-1111-1111-111111111111",
    ]
    assert result[0]["module_id"] == "demo.module1"
    assert "messages" not in result[0]


def test_cancel_task_marks_running_task_cancelled_and_idempotent(tmp_path, monkeypatch):
    """管理员停止生成：立即置 cancelled 终态、追加事件、幂等，且线程自然结束后不覆盖该状态。"""

    async def scenario():
        generation_service = FakeGenerationService()
        service = UserModuleAgentService(
            module_root=tmp_path / "user-modules",
            generation_service=generation_service,
        )
        release = threading.Event()

        def blocked_execute(**_kwargs):
            release.wait(timeout=5)  # 模拟 LLM 调用进行中
            return {"success": True, "result": "late"}

        monkeypatch.setattr(service, "_execute_expert", blocked_execute)
        created = await service.create_task(
            module_id="vendor.cancel",
            requirement="测试管理员停止生成",
            created_by="7",
            auth_token="token",
            model="demo-model",
            model_id=12,
            vendor_id=3,
        )
        for _ in range(200):
            state = await asyncio.to_thread(service._read_task_sync, created["task_id"])
            if state["status"] == "running":
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("agent task did not start")

        # 非创建者不可取消（与 answers 接口一致，按不存在处理）
        with pytest.raises(UserModuleAgentTaskNotFoundError):
            await service.cancel_task(created["task_id"], requester_id="8")

        cancelled = await service.cancel_task(created["task_id"], requester_id="7")
        assert cancelled["status"] == "cancelled"
        assert cancelled["error_code"] == "agent_task_cancelled"
        assert service.is_task_cancelled(created["task_id"]) is True
        assert "cancelled" in [message["type"] for message in cancelled["messages"]]

        # 幂等：对已终态任务重复取消原样返回
        again = await service.cancel_task(created["task_id"], requester_id="7")
        assert again["status"] == "cancelled"
        assert again["updated_at"] == cancelled["updated_at"]

        # 当前 LLM 调用结束后线程退出，failed/completed 更新被终态保护拒绝
        release.set()
        with service._threads_lock:
            worker = service._threads.get(created["task_id"])
        if worker is not None:
            worker.join(timeout=5)
        final = await asyncio.to_thread(service._read_task_sync, created["task_id"])
        assert final["status"] == "cancelled"
        assert final["error_code"] == "agent_task_cancelled"

    asyncio.run(scenario())


def test_background_adapter_check_cancelled(tmp_path):
    """迭代检查点：running 不抛；cancelled 或任务文件消失时抛 UserModuleAgentTaskCancelledError。"""
    from services.user_module_ask_user_adapter import BackgroundAskUserAdapter

    service = UserModuleAgentService(
        module_root=tmp_path / "user-modules",
        generation_service=FakeGenerationService(),
    )
    task_id = "44444444-4444-4444-4444-444444444444"
    service._task_path(task_id).write_text(
        json.dumps({"task_id": task_id, "status": "running", "created_by": "7"}),
        encoding="utf-8",
    )
    adapter = BackgroundAskUserAdapter(service, task_id)
    adapter.check_cancelled()  # running：放行

    service._update_task_sync(
        task_id,
        {"status": "cancelled", "error_code": "agent_task_cancelled", "error": "管理员已停止生成"},
    )
    with pytest.raises(UserModuleAgentTaskCancelledError):
        adapter.check_cancelled()

    # 任务文件消失（如被清理）视为已结束，避免线程空转
    service._task_path(task_id).unlink()
    with pytest.raises(UserModuleAgentTaskCancelledError):
        adapter.check_cancelled()
