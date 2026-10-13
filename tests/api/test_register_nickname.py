"""注册路径自动分配昵称回归测试。

背景：真实注册 SQL 在 perseids_server/services/auth_service.py（邮箱/手机两条
INSERT），曾漏带 nickname 字段导致新注册用户昵称为 NULL（兜底显示"用户{id}"）。
本测试 mock 掉 DB 依赖直接调用 AuthService.register，断言 INSERT 参数携带
随机趣味昵称（非空、末尾无数字）。
"""

import asyncio
from unittest.mock import MagicMock

from perseids_server.services import auth_service


def _register_email(monkeypatch, captured):
    """mock 全部 DB 依赖，走邮箱注册路径，返回 register 结果。"""

    # 注册配额直接放行（社区版默认上限 1，库里已有活跃用户会触发拦截）
    monkeypatch.setattr(
        "services.registration_quota.check_allowed", lambda active_count: (True, "")
    )

    users_model = MagicMock()
    users_model.get_active_count.return_value = 0
    users_model.get_by_email.return_value = None
    users_model.get_total_count.return_value = 1  # 非首个用户
    users_model.generate_unique_invite_code.return_value = "ABC123"
    users_model.generate_unique_nickname.return_value = "机智的熊猫"
    monkeypatch.setattr(auth_service, "UsersModel", users_model)

    verify_model = MagicMock()
    verify_model.verify_for_email.return_value = True
    monkeypatch.setattr(auth_service, "VerifyCodesModel", verify_model)

    monkeypatch.setattr(auth_service, "ComputingPowerModel", MagicMock())
    monkeypatch.setattr(auth_service, "LoginLogModel", MagicMock())

    # register 内是 `from model.database import execute_insert`，须 patch 源头
    import model.database as database

    def fake_execute_insert(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return 100

    monkeypatch.setattr(database, "execute_insert", fake_execute_insert)

    return auth_service.AuthService.register(
        phone=None,
        password="Test1234",
        verify_code="123456",
        email="newuser@example.com",
    )


def test_email_register_inserts_nickname(monkeypatch):
    captured = {}
    result = _register_email(monkeypatch, captured)
    assert result["success"] is True
    assert "nickname" in captured["sql"]
    # 昵称参数位于 email 之后：phone=None, email=..., nickname=...
    nickname = captured["params"][2]
    assert nickname == "机智的熊猫"
    assert not str(nickname)[-1].isdigit()


def test_phone_register_inserts_nickname(monkeypatch):
    """手机号注册同样必须携带昵称（两条注册 SQL 各自独立，防止回归只修一条）。"""
    captured = {}
    monkeypatch.setattr(
        "services.registration_quota.check_allowed", lambda active_count: (True, "")
    )

    users_model = MagicMock()
    users_model.get_active_count.return_value = 0
    users_model.get_by_phone.return_value = None
    users_model.get_total_count.return_value = 1
    users_model.generate_unique_invite_code.return_value = "ABC123"
    users_model.generate_unique_nickname.return_value = "认真的企鹅"
    monkeypatch.setattr(auth_service, "UsersModel", users_model)

    verify_model = MagicMock()
    verify_model.verify_for_phone.return_value = True
    monkeypatch.setattr(auth_service, "VerifyCodesModel", verify_model)

    monkeypatch.setattr(auth_service, "ComputingPowerModel", MagicMock())
    monkeypatch.setattr(auth_service, "LoginLogModel", MagicMock())

    import model.database as database

    def fake_execute_insert(sql, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return 101

    monkeypatch.setattr(database, "execute_insert", fake_execute_insert)

    result = auth_service.AuthService.register(
        phone="13900001111",
        password="Test1234",
        verify_code="123456",
    )
    assert result["success"] is True
    assert "nickname" in captured["sql"]
    nickname = captured["params"][1]  # phone 之后紧跟 nickname
    assert nickname == "认真的企鹅"
    assert not str(nickname)[-1].isdigit()
