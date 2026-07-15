"""剧本分段拆分 - API 端点单元测试。

覆盖测试方案 §2.7：
- compute_active_key 幂等键确定性
- _normalize_request_config model dict 拍平 + sequence_mode 校验
- GET /tasks/{id} 权限校验（X-User-Id != owner → 403）
- GET /tasks/{id}/result 仅 completed 可取（否则 409）
- GET /active-task 刷新恢复
- POST /tasks/{id}/resume 状态校验 + 检查点恢复路径
- POST /tasks/{id}/cancel 协作式取消 + 终态拒绝
- _resume_target_state 三路径（publishing/generating/queued）

用独立 FastAPI app + TestClient，model 层全部 monkeypatch，不连库。
"""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.script_split import (
    _normalize_request_config,
    _resume_target_state,
    compute_active_key,
    router,
)
from config.constant import ScriptSplitConstants


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def patch_to_thread(monkeypatch):
    """让 api.script_split 内的 asyncio.to_thread 同步执行并返回 awaitable。

    API 端点里是 `import asyncio; await asyncio.to_thread(fn, ...)`，
    patch 全局 asyncio.to_thread 后必须返回可 await 的值。
    """
    import asyncio as _asyncio_mod

    async def _fake(fn, *a, **kw):
        return fn(*a, **kw)

    monkeypatch.setattr(_asyncio_mod, "to_thread", _fake)


def _fake_task(**overrides):
    base = dict(
        id=1, user_id=7, status="generating", phase="segment_generation",
        progress=40, script_content="剧本",
    )
    base.update(overrides)
    task = SimpleNamespace(**base)
    task.to_public_status = lambda: {"task_id": task.id, "status": task.status}
    task.get_final_result = lambda: getattr(task, "_final", None)
    task.get_segment_plan = lambda: getattr(task, "_plan", None)
    return task


# ---------------- compute_active_key ----------------

class TestComputeActiveKey:
    def test_deterministic_for_same_input(self):
        cfg = {"model": "gemini-flash", "sequence_mode": "speed"}
        k1 = compute_active_key(1, "storyboard", 5, None, "abc", cfg)
        k2 = compute_active_key(1, "storyboard", 5, None, "abc", cfg)
        assert k1 == k2
        assert len(k1) == 64

    def test_different_user_different_key(self):
        cfg = {"model": "m"}
        k1 = compute_active_key(1, "storyboard", 5, None, "abc", cfg)
        k2 = compute_active_key(2, "storyboard", 5, None, "abc", cfg)
        assert k1 != k2

    def test_different_script_different_key(self):
        cfg = {"model": "m"}
        k1 = compute_active_key(1, "storyboard", 5, None, "sha-a", cfg)
        k2 = compute_active_key(1, "storyboard", 5, None, "sha-b", cfg)
        assert k1 != k2

    def test_config_order_invariant(self):
        """config 字段顺序不影响 key（json sort_keys）。"""
        k1 = compute_active_key(1, "s", 1, None, "x", {"a": 1, "b": 2})
        k2 = compute_active_key(1, "s", 1, None, "x", {"b": 2, "a": 1})
        assert k1 == k2


# ---------------- _normalize_request_config ----------------

class TestNormalizeRequestConfig:
    def test_model_dict_flattened(self):
        cfg = _normalize_request_config({"model": {"model": "gemini-flash", "model_id": 7}})
        assert cfg["model"] == "gemini-flash"
        assert isinstance(cfg["model"], str)

    def test_model_dict_with_name_key(self):
        cfg = _normalize_request_config({"model": {"name": "deepseek"}})
        assert cfg["model"] == "deepseek"

    def test_sequence_mode_default_speed(self):
        cfg = _normalize_request_config({})
        assert cfg["sequence_mode"] == "speed"

    def test_sequence_mode_quality_allowed_at_normalize(self):
        """_normalize 只做格式校验（quality 的商业版门禁在更上层）。"""
        cfg = _normalize_request_config({"sequence_mode": "QUALITY"})
        assert cfg["sequence_mode"] == "quality"

    def test_invalid_sequence_mode_raises(self):
        with pytest.raises(ValueError):
            _normalize_request_config({"sequence_mode": "turbo"})


# ---------------- _resume_target_state ----------------

class TestResumeTargetState:
    def test_has_final_result_targets_publishing(self):
        task = _fake_task(_final={"shot_groups": []})
        assert _resume_target_state(task) == ScriptSplitConstants.STATUS_PUBLISHING

    def test_phase_publishing_targets_publishing(self):
        task = _fake_task(phase="publishing")
        assert _resume_target_state(task) == ScriptSplitConstants.STATUS_PUBLISHING

    def test_has_plan_targets_generating(self):
        task = _fake_task(_plan={"segments": []})
        assert _resume_target_state(task) == ScriptSplitConstants.STATUS_GENERATING

    def test_no_checkpoint_targets_queued(self):
        task = _fake_task()
        assert _resume_target_state(task) == ScriptSplitConstants.STATUS_QUEUED


# ---------------- GET /tasks/{id} 权限 ----------------

class TestGetTaskStatus:
    def test_agent_bearer_token_owner_can_read(self, monkeypatch, patch_to_thread):
        task = _fake_task(user_id=7)
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        monkeypatch.setattr(
            "model.user_tokens.UserTokensModel.get_user_id_by_token",
            staticmethod(lambda token: 7 if token == "agent-auth" else None),
        )

        resp = _client().get(
            "/api/script-split/tasks/1",
            headers={"Authorization": "Bearer agent-auth"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "generating"

    def test_valid_authorization_wins_over_conflicting_browser_header(
        self, monkeypatch, patch_to_thread
    ):
        task = _fake_task(user_id=7)
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        monkeypatch.setattr(
            "model.user_tokens.UserTokensModel.get_user_id_by_token",
            staticmethod(lambda token: 7 if token == "agent-auth" else None),
        )

        resp = _client().get(
            "/api/script-split/tasks/1",
            headers={"Authorization": "Bearer agent-auth", "X-User-Id": "999"},
        )

        assert resp.status_code == 200

    def test_invalid_authorization_falls_back_to_browser_header(
        self, monkeypatch, patch_to_thread
    ):
        task = _fake_task(user_id=7)
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        monkeypatch.setattr(
            "model.user_tokens.UserTokensModel.get_user_id_by_token",
            staticmethod(lambda token: None),
        )

        resp = _client().get(
            "/api/script-split/tasks/1",
            headers={"Authorization": "Bearer expired", "X-User-Id": "7"},
        )

        assert resp.status_code == 200

    def test_invalid_agent_authorization_without_header_is_unauthorized(
        self, monkeypatch, patch_to_thread
    ):
        task = _fake_task(user_id=7)
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        monkeypatch.setattr(
            "model.user_tokens.UserTokensModel.get_user_id_by_token",
            staticmethod(lambda token: None),
        )

        resp = _client().get(
            "/api/script-split/tasks/1",
            headers={"Authorization": "Bearer expired"},
        )

        assert resp.status_code == 401
        assert resp.json()["error_code"] == "invalid_auth_token"

    def test_owner_can_read(self, monkeypatch, patch_to_thread):
        task = _fake_task(user_id=7)
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        resp = _client().get("/api/script-split/tasks/1", headers={"X-User-Id": "7"})
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "generating"

    def test_non_owner_forbidden(self, monkeypatch, patch_to_thread):
        task = _fake_task(user_id=7)
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        resp = _client().get("/api/script-split/tasks/1", headers={"X-User-Id": "999"})
        assert resp.status_code == 403

    def test_task_not_found(self, monkeypatch, patch_to_thread):
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: None))
        resp = _client().get("/api/script-split/tasks/1", headers={"X-User-Id": "7"})
        assert resp.status_code == 404


# ---------------- GET /tasks/{id}/result ----------------

class TestGetTaskResult:
    def test_agent_bearer_token_can_read_completed_result(
        self, monkeypatch, patch_to_thread
    ):
        task = _fake_task(
            user_id=7,
            status="completed",
            _final={"shot_groups": [{"shots": []}]},
        )
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        monkeypatch.setattr(
            "model.user_tokens.UserTokensModel.get_user_id_by_token",
            staticmethod(lambda token: 7),
        )

        resp = _client().get(
            "/api/script-split/tasks/1/result",
            headers={"Authorization": "Bearer agent-auth"},
        )

        assert resp.status_code == 200
    def test_completed_returns_final(self, monkeypatch, patch_to_thread):
        task = _fake_task(status="completed", _final={"shot_groups": [{"shots": []}]})
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        resp = _client().get("/api/script-split/tasks/1/result", headers={"X-User-Id": "7"})
        assert resp.status_code == 200
        assert resp.json()["data"]["shot_groups"] is not None

    def test_non_completed_returns_409(self, monkeypatch, patch_to_thread):
        task = _fake_task(status="paused")
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        resp = _client().get("/api/script-split/tasks/1/result", headers={"X-User-Id": "7"})
        assert resp.status_code == 409


# ---------------- GET /active-task ----------------

class TestGetActiveTask:
    def test_agent_bearer_token_can_read_active_task(
        self, monkeypatch, patch_to_thread
    ):
        task = _fake_task(user_id=7)
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_active_by_source",
            staticmethod(lambda st, sid, key: task),
        )
        monkeypatch.setattr(
            "model.user_tokens.UserTokensModel.get_user_id_by_token",
            staticmethod(lambda token: 7),
        )

        resp = _client().get(
            "/api/script-split/active-task?source_type=storyboard&source_id=5",
            headers={"Authorization": "Bearer agent-auth"},
        )

        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "generating"
    def test_returns_active_task(self, monkeypatch, patch_to_thread):
        task = _fake_task(user_id=7)
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_active_by_source",
            staticmethod(lambda st, sid, key: task))
        resp = _client().get(
            "/api/script-split/active-task?source_type=storyboard&source_id=5",
            headers={"X-User-Id": "7"})
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "generating"

    def test_no_active_returns_null(self, monkeypatch, patch_to_thread):
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_active_by_source",
            staticmethod(lambda st, sid, key: None))
        resp = _client().get(
            "/api/script-split/active-task?source_type=storyboard&source_id=5",
            headers={"X-User-Id": "7"})
        assert resp.status_code == 200
        assert resp.json()["data"] is None

    def test_missing_source_params_400(self):
        resp = _client().get("/api/script-split/active-task", headers={"X-User-Id": "7"})
        assert resp.status_code == 400


# ---------------- POST /tasks/{id}/resume ----------------

class TestResumeTask:
    def test_agent_bearer_token_can_resume_and_persists_normalized_token(
        self, monkeypatch, patch_to_thread
    ):
        task = _fake_task(user_id=7, status="paused", _plan={"segments": []})
        saved = []
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        monkeypatch.setattr(
            "model.user_tokens.UserTokensModel.get_user_id_by_token",
            staticmethod(lambda token: 7),
        )
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.update_status", staticmethod(lambda *a, **kw: None))
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.save_field",
            staticmethod(lambda tid, **kw: saved.append(kw)),
        )
        monkeypatch.setattr(
            "api.script_split.ScriptSplitSegmentModel.reset_retry_budget",
            staticmethod(lambda tid: None),
        )

        resp = _client().post(
            "/api/script-split/tasks/1/resume",
            headers={"Authorization": "Bearer agent-auth"},
        )

        assert resp.status_code == 200
        assert {item.get("auth_token") for item in saved} == {"agent-auth"}
    def test_paused_resumes(self, monkeypatch, patch_to_thread):
        task = _fake_task(status="paused", _plan={"segments": []})
        updates = []
        monkeypatch.setattr(
            "model.user_tokens.UserTokensModel.get_user_id_by_token",
            staticmethod(lambda token: 7),
        )
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        monkeypatch.setattr("api.script_split.ScriptSplitTaskModel.update_status",
                            staticmethod(lambda tid, status, **kw: updates.append((status, kw))))
        monkeypatch.setattr("api.script_split.ScriptSplitTaskModel.save_field",
                            staticmethod(lambda tid, **kw: None))
        monkeypatch.setattr("api.script_split.ScriptSplitSegmentModel.reset_retry_budget",
                            staticmethod(lambda tid: None))
        resp = _client().post("/api/script-split/tasks/1/resume",
                              headers={"X-User-Id": "7", "Authorization": "Bearer new-tok"})
        assert resp.status_code == 200
        # paused + 有 plan → 恢复到 generating
        assert any(s == ScriptSplitConstants.STATUS_GENERATING for s, _ in updates)

    def test_running_status_rejected_409(self, monkeypatch, patch_to_thread):
        task = _fake_task(status="generating")
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        resp = _client().post("/api/script-split/tasks/1/resume", headers={"X-User-Id": "7"})
        assert resp.status_code == 409

    def test_non_owner_forbidden(self, monkeypatch, patch_to_thread):
        task = _fake_task(user_id=7, status="paused")
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        resp = _client().post("/api/script-split/tasks/1/resume", headers={"X-User-Id": "999"})
        assert resp.status_code == 403


# ---------------- POST /tasks/{id}/cancel ----------------

class TestCancelTask:
    def test_agent_bearer_token_can_cancel(self, monkeypatch, patch_to_thread):
        task = _fake_task(user_id=7, status="generating")
        requested = []
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        monkeypatch.setattr(
            "model.user_tokens.UserTokensModel.get_user_id_by_token",
            staticmethod(lambda token: 7),
        )
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.request_cancel",
            staticmethod(lambda tid: requested.append(tid)),
        )
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.update_status", staticmethod(lambda *a, **kw: None))

        resp = _client().post(
            "/api/script-split/tasks/1/cancel",
            headers={"Authorization": "Bearer agent-auth"},
        )

        assert resp.status_code == 200
        assert requested == [1]
    def test_cancel_sets_cancelling(self, monkeypatch, patch_to_thread):
        task = _fake_task(status="generating")
        requested = []
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        monkeypatch.setattr("api.script_split.ScriptSplitTaskModel.request_cancel",
                            staticmethod(lambda tid: requested.append(tid)))
        monkeypatch.setattr("api.script_split.ScriptSplitTaskModel.update_status",
                            staticmethod(lambda tid, status, **kw: None))
        resp = _client().post("/api/script-split/tasks/1/cancel", headers={"X-User-Id": "7"})
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "cancelling"
        assert requested == [1]

    def test_terminal_status_rejected_409(self, monkeypatch, patch_to_thread):
        task = _fake_task(status="completed")
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        resp = _client().post("/api/script-split/tasks/1/cancel", headers={"X-User-Id": "7"})
        assert resp.status_code == 409

    def test_non_owner_forbidden(self, monkeypatch, patch_to_thread):
        task = _fake_task(user_id=7, status="generating")
        monkeypatch.setattr(
            "api.script_split.ScriptSplitTaskModel.get_by_id", staticmethod(lambda tid: task))
        resp = _client().post("/api/script-split/tasks/1/cancel", headers={"X-User-Id": "999"})
        assert resp.status_code == 403
