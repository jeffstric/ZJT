"""剧本分段拆分 - engine 单步执行单元测试。

覆盖测试方案 §2.5（核心）：
- step_plan：已有计划跳过、空剧本、取消、鉴权失效、重试上界、成功路径
- step_publish：非 storyboard 直接 completed、storyboard 幂等（已全发布）、冲突
- 异常类构造与 code 传递

engine 是 async 函数，调 model 层与 LLM；model 层用 monkeypatch 替换，
plan_segments（在函数内部 import）用 monkeypatch 替换 llm.script_segment_planner.plan_segments。
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from config.constant import ScriptSplitConstants
from services import script_split_engine as engine
from services.script_split_engine import (
    CancelledByUser,
    EngineError,
    TaskPaused,
    WaitingAuth,
    step_plan,
    step_publish,
)


def _run(coro):
    return asyncio.run(coro)


async def _await_value(value):
    """把同步值包成 awaitable，用于替换 asyncio.to_thread。"""
    return value


class _FakeTask:
    """内存 task 对象，模拟 ScriptSplitTask 的接口（get_request_config 等）。"""

    def __init__(self, **overrides):
        self.id = 1
        self.status = "planning"
        self.script_content = "场景一：清晨，小明走进客厅。\n\n场景二：黄昏，小红到来。"
        self.auth_token = "tok"
        self._cfg = {"source": "storyboard", "model": "gemini-flash",
                     "storyboard_id": 5, "world_id": 7}
        self._plan = None
        self._final = None
        for k, v in overrides.items():
            if k == "request_config":
                self._cfg = v
            elif k == "segment_plan":
                self._plan = v
            elif k == "final_result":
                self._final = v
            else:
                setattr(self, k, v)

    def get_request_config(self):
        return self._cfg

    def get_segment_plan(self):
        return self._plan

    def get_final_result(self):
        return self._final


def _task(**overrides):
    return _FakeTask(**overrides)


@pytest.fixture
def patch_models(monkeypatch):
    """替换 engine 内用到的 model 层调用，记录调用。"""
    calls = {"update_plan": [], "save_field": [], "replace_all": [],
             "update_status": [], "count_scenes": None, "list_scenes": None}

    def fake_update_plan(task_id, plan, plan_revision, total_segment_count):
        calls["update_plan"].append((task_id, total_segment_count))

    def fake_save_field(task_id, **fields):
        calls["save_field"].append((task_id, fields))

    def fake_replace_all(task_id, segs):
        calls["replace_all"].append((task_id, len(segs)))

    def fake_update_status(task_id, status, **kw):
        calls["update_status"].append((task_id, status, kw))

    monkeypatch.setattr(engine.ScriptSplitTaskModel, "update_plan", staticmethod(fake_update_plan))
    monkeypatch.setattr(engine.ScriptSplitTaskModel, "save_field", staticmethod(fake_save_field))
    monkeypatch.setattr(engine.ScriptSplitSegmentModel, "replace_all", staticmethod(fake_replace_all))
    monkeypatch.setattr(engine.ScriptSplitTaskModel, "update_status", staticmethod(fake_update_status))
    # _is_cancelled 默认返回 False（取消测试单独覆盖）
    monkeypatch.setattr(engine.ScriptSplitTaskModel, "is_cancel_requested",
                        staticmethod(lambda tid: False))
    return calls


# ---------------- 异常类 ----------------

class TestEngineExceptions:
    def test_engine_error_carries_code_and_message(self):
        e = EngineError("empty_script", "剧本为空")
        assert e.code == "empty_script"
        assert e.message == "剧本为空"
        assert "[empty_script]" in str(e)

    def test_task_paused_inherits_engine_error(self):
        e = TaskPaused("plan_failed", "重试耗尽")
        assert isinstance(e, EngineError)
        assert e.code == "plan_failed"

    def test_cancelled_by_user_default_code(self):
        e = CancelledByUser()
        assert e.code == "cancelled"
        assert isinstance(e, EngineError)

    def test_waiting_auth_default_message(self):
        e = WaitingAuth()
        assert e.code == "waiting_auth"
        assert "刷新页面" in e.message


# ---------------- step_plan ----------------

class TestStepPlan:
    def test_skips_when_plan_already_exists(self, patch_models, monkeypatch):
        """已有分段计划（断点续传）→ 不重复调 LLM，直接返回。"""
        called = []

        async def fake_plan_segments(**kw):
            called.append(kw)
            return {}, "stop"

        monkeypatch.setattr("llm.script_segment_planner.plan_segments", fake_plan_segments)
        task = _task(segment_plan={"segments": [{"segment_id": "seg_1", "block_ids": ["block_0001"]}]})

        _run(step_plan(task))

        assert called == []  # 未调 LLM
        assert patch_models["update_status"] == []  # 未改状态

    def test_empty_script_raises_terminal(self, patch_models, monkeypatch):
        """空剧本 → EngineError(empty_script)，属 terminal_code → worker 会进 failed。"""
        task = _task(script_content="")

        with pytest.raises(EngineError) as exc_info:
            _run(step_plan(task))
        assert exc_info.value.code == "empty_script"

    def test_cancel_requested_raises_cancelled(self, patch_models, monkeypatch):
        """取消标记生效 → 抛 CancelledByUser。"""
        monkeypatch.setattr(engine.ScriptSplitTaskModel, "is_cancel_requested",
                            staticmethod(lambda tid: True))
        task = _task()

        with pytest.raises(CancelledByUser):
            _run(step_plan(task))

    def test_auth_error_raises_waiting_auth(self, patch_models, monkeypatch):
        """plan_segments 抛鉴权类错误 → WaitingAuth。"""
        async def fake_plan_segments(**kw):
            raise RuntimeError("401 unauthorized")

        monkeypatch.setattr("llm.script_segment_planner.plan_segments", fake_plan_segments)
        # 屏蔽日志写入（内部 async 落盘）
        monkeypatch.setattr("llm.script_segment_planner.write_plan_validation_log",
                            AsyncMock(return_value=None))
        task = _task()

        with pytest.raises(WaitingAuth):
            _run(step_plan(task))

    def test_plan_retries_exhausted_raises_task_paused(self, patch_models, monkeypatch):
        """连续 PLAN_MAX_RETRIES 次返回非法 plan → TaskPaused（保留检查点）。"""
        async def fake_plan_segments(**kw):
            # 返回一个不合法的 plan（缺 segments）
            return {"segments": []}, "stop"

        monkeypatch.setattr("llm.script_segment_planner.plan_segments", fake_plan_segments)
        monkeypatch.setattr("llm.script_segment_planner.write_plan_validation_log",
                            AsyncMock(return_value=None))
        task = _task()

        with pytest.raises(TaskPaused) as exc_info:
            _run(step_plan(task))
        assert exc_info.value.code == "plan_failed"

    def test_successful_plan_persists_and_transitions(self, patch_models, monkeypatch):
        """成功规划 → 持久化计划 + 写 segment 检查点 + 转 generating（progress=10）。"""
        anchors_blocks = ["场景一：清晨。", "场景二：黄昏。"]

        async def fake_plan_segments(**kw):
            return {"segments": [
                {"segment_id": "seg_1", "block_ids": ["block_0001"]},
                {"segment_id": "seg_2", "block_ids": ["block_0002"]},
            ]}, "stop"

        monkeypatch.setattr("llm.script_segment_planner.plan_segments", fake_plan_segments)
        monkeypatch.setattr("llm.script_segment_planner.write_plan_validation_log",
                            AsyncMock(return_value=None))
        task = _task(script_content="\n\n".join(anchors_blocks))

        _run(step_plan(task))

        # 持久化了 2 段
        assert patch_models["update_plan"][0][1] == 2
        assert patch_models["replace_all"][0][1] == 2
        # 状态转到 generating
        status_calls = patch_models["update_status"]
        assert any(s == ScriptSplitConstants.STATUS_GENERATING for _, s, _ in status_calls)


# ---------------- step_publish ----------------

class TestStepPublish:
    def test_non_storyboard_completes_directly(self, patch_models, monkeypatch):
        """非 storyboard 来源（video_workflow/cli）→ 直接 completed，不调 create_scenes。"""
        task = _task(request_config={"source": "video_workflow"})

        _run(step_publish(task))

        statuses = [s for _, s, _ in patch_models["update_status"]]
        assert ScriptSplitConstants.STATUS_COMPLETED in statuses

    def test_storyboard_already_published_completes(self, patch_models, monkeypatch):
        """storyboard 来源且已全部发布（count==expected）→ 直接 completed（幂等）。"""
        final_result = {"shot_groups": [{"shots": [{"shot_id": "s1"}, {"shot_id": "s2"}]}]}
        task = _task(final_result=final_result, request_config={"source": "storyboard", "storyboard_id": 5})

        from model.storyboard import StoryboardModel
        monkeypatch.setattr(StoryboardModel, "count_scenes_by_split_task",
                            staticmethod(lambda tid: 2))
        # to_thread 返回 awaitable 包装同步结果
        monkeypatch.setattr(engine.asyncio, "to_thread",
                            lambda fn, *a, **kw: _await_value(fn(*a, **kw)))

        _run(step_publish(task))
        statuses = [s for _, s, _ in patch_models["update_status"]]
        assert ScriptSplitConstants.STATUS_COMPLETED in statuses

    def test_storyboard_partial_publish_raises_conflict(self, patch_models, monkeypatch):
        """storyboard 来源但已有分镜数 ≠ 预期 → publish_conflict（停止避免重复）。"""
        final_result = {"shot_groups": [{"shots": [{"shot_id": "s1"}, {"shot_id": "s2"}]}]}
        task = _task(final_result=final_result, request_config={"source": "storyboard", "storyboard_id": 5})

        from model.storyboard import StoryboardModel
        monkeypatch.setattr(StoryboardModel, "count_scenes_by_split_task",
                            staticmethod(lambda tid: 1))
        monkeypatch.setattr(engine.asyncio, "to_thread",
                            lambda fn, *a, **kw: _await_value(fn(*a, **kw)))

        with pytest.raises(EngineError) as exc_info:
            _run(step_publish(task))
        assert exc_info.value.code == "publish_conflict"

    def test_storyboard_missing_id_raises(self, patch_models, monkeypatch):
        """storyboard 任务缺 storyboard_id → no_storyboard_id。"""
        task = _task(final_result={"shot_groups": []},
                     request_config={"source": "storyboard"})  # 无 storyboard_id

        with pytest.raises(EngineError) as exc_info:
            _run(step_publish(task))
        assert exc_info.value.code == "no_storyboard_id"

    def test_storyboard_no_final_result_raises(self, patch_models, monkeypatch):
        """storyboard 任务无 final_result → no_final_result。"""
        task = _task(final_result=None,
                     request_config={"source": "storyboard", "storyboard_id": 5})

        with pytest.raises(EngineError) as exc_info:
            _run(step_publish(task))
        assert exc_info.value.code == "no_final_result"
