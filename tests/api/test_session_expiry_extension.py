"""会话活动顺延过期时间：_extend_session_expiry / _session_expire_hours 行为验证。"""

from datetime import datetime, timedelta

from config.constant import SessionHistoryConstants


def test_script_session_expire_hours_is_72():
    """剧本会话保留期为 3 天（72 小时）"""
    assert SessionHistoryConstants.SESSION_EXPIRE_HOURS_SCRIPT == 72


def test_session_expire_hours_by_type():
    from api import script_writer as sw

    assert sw._session_expire_hours(1) == SessionHistoryConstants.SESSION_EXPIRE_HOURS_SCRIPT
    assert sw._session_expire_hours(2) == SessionHistoryConstants.SESSION_EXPIRE_HOURS_MARKETING


def test_extend_session_expiry_script_session(monkeypatch):
    from api import script_writer as sw

    calls = {}

    def _fake_update_metadata(session_id, expires_at=None):
        calls["session_id"] = session_id
        calls["expires_at"] = expires_at
        return 1

    monkeypatch.setattr(
        "model.chat_sessions.ChatSessionsModel.update_metadata", _fake_update_metadata
    )

    before = datetime.now()
    sw._extend_session_expiry("sess-1", 1)
    after = datetime.now()

    assert calls["session_id"] == "sess-1"
    assert before + timedelta(hours=72) <= calls["expires_at"] <= after + timedelta(hours=72)


def test_extend_session_expiry_marketing_session(monkeypatch):
    from api import script_writer as sw

    calls = {}

    def _fake_update_metadata(session_id, expires_at=None):
        calls["session_id"] = session_id
        calls["expires_at"] = expires_at
        return 1

    monkeypatch.setattr(
        "model.chat_sessions.ChatSessionsModel.update_metadata", _fake_update_metadata
    )

    before = datetime.now()
    sw._extend_session_expiry("sess-2", 2)
    after = datetime.now()

    assert before + timedelta(hours=336) <= calls["expires_at"] <= after + timedelta(hours=336)
