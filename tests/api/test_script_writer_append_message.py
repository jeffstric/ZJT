"""append-message 接口：__PENDING_TASK__ 标记必须落库为 pending_task 类型。

背景（2026-10-28 事故，会话 3941fc69）：前端直连生成路径把 __PENDING_TASK__
标记经 append-message 写入历史时被强制存成 message_type='normal'，而后端
replace_pending_task（model/chat_messages.py）只匹配 message_type='pending_task'，
导致轮询完成时原位替换永远命中 0 行，只能 append 兜底 + 事后清理。
pm_agent 路径（script_writer_core/agents/pm_agent.py）存的就是 pending_task，
两条路径必须一致。
"""

import asyncio
from types import SimpleNamespace

from api import script_writer as sw


class _FakeRecorder:
    """捕获 append_message 调用参数，替代真实落库。"""

    def __init__(self, captured):
        self._captured = captured

    def append_message(self, **kwargs):
        self._captured.append(kwargs)


def _patch_common(monkeypatch, captured):
    from model.chat_sessions import ChatSessionsModel
    from script_writer_core.conversation_recorder import ConversationRecorder

    session = SimpleNamespace(user_id=1, session_type=2)
    monkeypatch.setattr(
        ChatSessionsModel, "get_by_session_id", staticmethod(lambda sid: session)
    )
    monkeypatch.setattr(sw, "ensure_owner", lambda uid, auth_uid: None)
    monkeypatch.setattr(sw, "get_auth_user_id", lambda request: 1)
    monkeypatch.setattr(
        ConversationRecorder,
        "__new__",
        lambda cls, *a, **kw: _FakeRecorder(captured),
    )
    monkeypatch.setattr(
        sw.session_storage, "invalidate_cache", lambda sid: None
    )
    monkeypatch.setattr(sw, "_extend_session_expiry", lambda sid, st: None)


def _call(role, content, captured, monkeypatch):
    _patch_common(monkeypatch, captured)
    # __wrapped__ 绕过 require_permission 装饰器，单测只关心消息类型判定逻辑
    return asyncio.run(
        sw.append_session_message.__wrapped__(
            SimpleNamespace(), "s-1", SimpleNamespace(role=role, content=content)
        )
    )


def test_append_pending_task_marker_stored_as_pending_task(monkeypatch):
    captured = []
    resp = _call(
        "assistant",
        "__PENDING_TASK__:video_task_submitted:[65321]",
        captured,
        monkeypatch,
    )
    assert resp.status_code == 200
    assert len(captured) == 1
    assert captured[0]["message_type"] == "pending_task"
    assert captured[0]["source"] == "frontend"


def test_append_normal_message_stays_normal(monkeypatch):
    captured = []
    resp = _call("assistant", "视频生成好了", captured, monkeypatch)
    assert resp.status_code == 200
    assert len(captured) == 1
    assert captured[0]["message_type"] == "normal"


def test_append_user_pending_like_content_stays_normal(monkeypatch):
    # 只有 assistant 角色的 __PENDING_TASK__ 标记才是 pending_task，
    # 用户消息里出现同名文本不应被改写类型
    captured = []
    resp = _call("user", "__PENDING_TASK__:video_task_submitted:[1]", captured, monkeypatch)
    assert resp.status_code == 200
    assert captured[0]["message_type"] == "normal"
