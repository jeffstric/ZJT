"""管理员设置用户备注接口（PUT /api/admin/users/{id}/remark）回归测试。

覆盖：成功保存/清除备注、备注超长 400、目标用户不存在 404、
非管理员 403、未登录 401。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api import admin as admin_api


def _run_as_admin(monkeypatch, user_id, remark, *, user_exists=True):
    """mock 鉴权为管理员，直接调用端点函数。"""

    async def fake_require_admin(auth_token):
        return SimpleNamespace(id=1, role="admin")

    monkeypatch.setattr(admin_api, "require_admin", fake_require_admin)

    users_model = MagicMock()
    users_model.get_by_id.return_value = SimpleNamespace(id=user_id) if user_exists else None
    users_model.update_remark.return_value = 1
    monkeypatch.setattr(admin_api, "UsersModel", users_model)
    monkeypatch.setattr(admin_api, "UserTokensModel", MagicMock())

    return asyncio.run(
        admin_api.admin_update_user_remark(
            user_id=user_id,
            request=SimpleNamespace(remark=remark),
            auth_token="Bearer test",
        )
    )


def test_save_remark_success(monkeypatch):
    result = _run_as_admin(monkeypatch, 2, "重要客户")
    assert result["code"] == 0
    assert result["data"]["remark"] == "重要客户"
    admin_api.UsersModel.update_remark.assert_called_once_with(2, "重要客户")


def test_save_remark_trims_whitespace(monkeypatch):
    result = _run_as_admin(monkeypatch, 2, "  需要回访  ")
    assert result["code"] == 0
    assert result["data"]["remark"] == "需要回访"
    admin_api.UsersModel.update_remark.assert_called_once_with(2, "需要回访")


def test_clear_remark_with_empty_string(monkeypatch):
    # 传空串 = 清除备注（model 层落 NULL）
    result = _run_as_admin(monkeypatch, 2, "")
    assert result["code"] == 0
    assert result["data"]["remark"] == ""
    admin_api.UsersModel.update_remark.assert_called_once_with(2, "")


def test_remark_too_long_rejected(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        _run_as_admin(monkeypatch, 2, "a" * 501)
    assert exc_info.value.status_code == 400
    assert "500" in str(exc_info.value.detail)
    admin_api.UsersModel.update_remark.assert_not_called()


def test_remark_target_user_not_found(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        _run_as_admin(monkeypatch, 999, "备注", user_exists=False)
    assert exc_info.value.status_code == 404
    admin_api.UsersModel.update_remark.assert_not_called()


def test_remark_rejected_for_non_admin(monkeypatch):
    """非管理员：require_admin 内部查 token → 用户角色为 user → 403"""
    users_model = MagicMock()
    users_model.get_by_id.return_value = SimpleNamespace(id=9, role="user")
    monkeypatch.setattr(admin_api, "UsersModel", users_model)
    tokens_model = MagicMock()
    tokens_model.get_user_id_by_token.return_value = 9
    monkeypatch.setattr(admin_api, "UserTokensModel", tokens_model)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            admin_api.admin_update_user_remark(
                user_id=2,
                request=SimpleNamespace(remark="备注"),
                auth_token="Bearer test",
            )
        )
    assert exc_info.value.status_code == 403
    users_model.update_remark.assert_not_called()


def test_remark_rejected_without_token(monkeypatch):
    """未登录：token 无效 → 401"""
    users_model = MagicMock()
    monkeypatch.setattr(admin_api, "UsersModel", users_model)
    tokens_model = MagicMock()
    tokens_model.get_user_id_by_token.return_value = None
    monkeypatch.setattr(admin_api, "UserTokensModel", tokens_model)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            admin_api.admin_update_user_remark(
                user_id=2,
                request=SimpleNamespace(remark="备注"),
                auth_token="Bearer test",
            )
        )
    assert exc_info.value.status_code == 401
    users_model.update_remark.assert_not_called()
