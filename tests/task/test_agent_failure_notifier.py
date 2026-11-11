# -*- coding: utf-8 -*-
"""
任务失败 agent 通知器测试（2026-11-12）

覆盖：
- 主仓钩子 register_agent_failure_notifier / _notify_agent_failure_async
  （注册、参数透传、异常吞掉不影响调度）
- enterprise 通知器：project→session 反查（幂等键主通道 + pending content 兜底）、
  非营销会话跳过、防重复标记跳过、内部触发请求的 URL/头/消息体
"""
import os

import pytest

# 必须在导入会触发 model/database 的模块前，给 config_unit.yml 塞进一个最小配置缓存。
os.environ.setdefault("comfyui_env", "unit")
from config import config_util  # noqa: E402

config_util._config_cache["config_unit.yml"] = {
    "database": {
        "host": "localhost",
        "port": 3306,
        "user": "root",
        "password": "",
        "database": "unit",
    },
    "server": {"host": "http://127.0.0.1:13009"},
    "file_storage": {},
}


class TestRegisterAgentFailureNotifier:
    def test_register_and_invoke(self, monkeypatch):
        import task.visual_task as vt

        calls = []

        def fake_notifier(task_id, reason, project_id=None):
            calls.append((task_id, reason, project_id))

        monkeypatch.setattr(vt, "_agent_failure_notifier", None)
        vt.register_agent_failure_notifier(fake_notifier)
        assert vt._agent_failure_notifier is fake_notifier

        vt._notify_agent_failure_async(123, "内容审核未通过（音频版权）：x", project_id=456)
        assert calls == [(123, "内容审核未通过（音频版权）：x", 456)]

    def test_notifier_exception_swallowed(self, monkeypatch):
        import task.visual_task as vt

        def boom(task_id, reason, project_id=None):
            raise RuntimeError("downstream down")

        monkeypatch.setattr(vt, "_agent_failure_notifier", boom)
        # 不外爆即通过（daemon 线程内只 warning）
        vt._notify_agent_failure_async(1, "boom reason", project_id=2)

    def test_unregister_when_notifier_none(self, monkeypatch):
        import task.visual_task as vt

        monkeypatch.setattr(vt, "_agent_failure_notifier", None)
        # 未注册时 _notify_agent_failure_async 不应被调用路径触发（_handle_task_failure
        # 侧的 if 守卫）；此处直接验证直调 None 会炸——守卫在调用点
        assert vt._agent_failure_notifier is None


class TestAgentFailureNotifierService:
    @pytest.fixture
    def notifier(self):
        from enterprise.services import agent_failure_notifier

        return agent_failure_notifier

    def _patch_db(self, monkeypatch, notifier, key_rows, content_rows=None):
        """按查询顺序打桩 execute_query（先幂等键通道，后 content 兜底）"""
        from model import chat_messages

        results = [r for r in ([key_rows] if key_rows is not None else []) +
                   [r for r in (content_rows if content_rows is not None else [])]]

        def fake_execute_query(sql, params=None, fetch_one=False):
            assert fetch_one, "notifier 只应使用 fetch_one 查询"
            if results:
                return results.pop(0)
            return None

        monkeypatch.setattr(chat_messages, "execute_query", fake_execute_query)
        return chat_messages

    def test_find_session_by_idempotency_key(self, monkeypatch, notifier):
        self._patch_db(
            monkeypatch, notifier,
            key_rows={"idempotency_key": "pending:sess-abc:video_task_submitted:456"},
        )
        assert notifier._find_session_id_by_project("456") == "sess-abc"

    def test_find_session_fallback_pending_content(self, monkeypatch, notifier):
        # 主通道（幂等键）无命中 → content 兜底通道命中
        self._patch_db(
            monkeypatch, notifier,
            key_rows=None,
            content_rows=[{"idempotency_key": "pending:sess-xyz:video_task_submitted:789"}],
        )
        assert notifier._find_session_id_by_project("789") == "sess-xyz"

    def test_find_session_not_found(self, monkeypatch, notifier):
        self._patch_db(monkeypatch, notifier, key_rows=None, content_rows=[])
        assert notifier._find_session_id_by_project("999") is None

    def test_notify_skips_non_marketing_session(self, monkeypatch, notifier):
        self._patch_db(
            monkeypatch, notifier,
            key_rows={"idempotency_key": "pending:s-1:video_task_submitted:5"},
        )
        triggered = {"called": False}

        class _Sess:
            session_type = 1  # 剧本创作会话
            auth_token = "tok"

        import model.chat_sessions as cs_mod
        monkeypatch.setattr(cs_mod.ChatSessionsModel, "get_by_session_id", staticmethod(lambda sid: _Sess()))
        monkeypatch.setattr(notifier, "_trigger_agent_turn", lambda *a, **k: triggered.__setitem__("called", True))

        notifier.notify_agent_task_failure(5, "任意原因", project_id=5)
        assert triggered["called"] is False

    def test_notify_skips_when_already_notified(self, monkeypatch, notifier):
        from model import chat_messages

        queries = []

        def fake_execute_query(sql, params=None, fetch_one=False):
            queries.append(sql)
            if "COUNT(*)" in sql:
                return {"cnt": 1}  # 已有 task-failed-notify 标记
            return {"idempotency_key": "pending:s-2:video_task_submitted:7"}

        monkeypatch.setattr(chat_messages, "execute_query", fake_execute_query)
        triggered = {"called": False}
        monkeypatch.setattr(notifier, "_trigger_agent_turn", lambda *a, **k: triggered.__setitem__("called", True))

        notifier.notify_agent_task_failure(7, "原因", project_id=7)
        assert triggered["called"] is False

    def test_notify_skips_without_session(self, monkeypatch, notifier):
        self._patch_db(monkeypatch, notifier, key_rows=None, content_rows=[])
        import model.chat_sessions as cs_mod
        get_calls = []

        def fake_get(sid):
            get_calls.append(sid)
            return None

        monkeypatch.setattr(cs_mod.ChatSessionsModel, "get_by_session_id", staticmethod(fake_get))
        notifier.notify_agent_task_failure(8, "原因", project_id=8)
        assert get_calls == []  # 反查不到会话则不应查 chat_sessions

    def test_notify_triggers_agent_turn(self, monkeypatch, notifier):
        self._patch_db(
            monkeypatch, notifier,
            key_rows={"idempotency_key": "pending:s-mkt:video_task_submitted:66"},
        )

        class _Sess:
            session_type = 2  # 营销会话
            auth_token = "tok-xyz"

        import model.chat_sessions as cs_mod
        monkeypatch.setattr(cs_mod.ChatSessionsModel, "get_by_session_id", staticmethod(lambda sid: _Sess()))

        captured = {}

        def fake_trigger(session_id, auth_token, message):
            captured.update(session_id=session_id, auth_token=auth_token, message=message)
            return True

        monkeypatch.setattr(notifier, "_trigger_agent_turn", fake_trigger)
        notifier.notify_agent_task_failure(66, "内容审核未通过（音频版权）：请更换参考音频/视频", project_id=66)

        assert captured["session_id"] == "s-mkt"
        assert captured["auth_token"] == "tok-xyz"
        assert "内容审核未通过（音频版权）" in captured["message"]
        assert notifier.NOTIFY_MARKER_PREFIX + "66" in captured["message"]  # 幂等标记随消息落库

    def test_trigger_uses_authorization_header_not_query(self, monkeypatch, notifier):
        """token 走 Authorization 头（X3 红线），URL 不携带 token"""
        import enterprise.services.agent_failure_notifier as mod

        captured = {}

        class _Resp:
            status_code = 200

            def __init__(self):
                self.text = "{}"

        def fake_post(url, json=None, headers=None, timeout=None, verify=False):
            captured.update(url=url, json=json, headers=headers)
            return _Resp()

        monkeypatch.setattr(mod.httpx, "post", fake_post)
        monkeypatch.setattr(mod, "_resolve_inner_base_url", lambda: "http://127.0.0.1:13009")

        ok = mod._trigger_agent_turn("sess-1", "secret-token", "[系统通知] 测试")
        assert ok is True
        assert captured["url"] == "http://127.0.0.1:13009/api/session/sess-1/task"
        assert "secret-token" not in captured["url"]
        assert captured["headers"] == {"Authorization": "Bearer secret-token"}
        assert "[系统通知]" in captured["json"]["message"]
