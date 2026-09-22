"""管理员更新用户状态接口的激活用户数配额回归测试。

覆盖口径：用户从不活跃状态（禁用 0 / 待审核 2）转为正常（1）时校验
激活用户数配额（社区版 COMMUNITY_MAX_ACTIVE_USERS=1）；禁用、已是正常、
非法状态值不触发配额；管理员不能将自己置为禁用/待审核。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from api import admin as admin_api
from config.constant import COMMUNITY_MAX_ACTIVE_USERS


@pytest.fixture(autouse=True)
def _reset_quota_provider():
    from services import registration_quota

    registration_quota.reset_provider()
    yield
    registration_quota.reset_provider()


def _run(monkeypatch, user_id, status, *, current_status=0, active_count=0):
    """直接调用端点函数；mock 鉴权与模型层。"""

    async def fake_require_admin(auth_token):
        return SimpleNamespace(id=1, role="admin")

    monkeypatch.setattr(admin_api, "require_admin", fake_require_admin)

    users_model = MagicMock()
    users_model.get_by_id.return_value = SimpleNamespace(
        id=user_id, status=current_status
    )
    users_model.get_active_count.return_value = active_count
    users_model.update_status.return_value = True
    monkeypatch.setattr(admin_api, "UsersModel", users_model)
    monkeypatch.setattr(admin_api, "UserTokensModel", MagicMock())

    return asyncio.run(
        admin_api.admin_update_user_status(
            user_id=user_id,
            request=SimpleNamespace(status=status),
            auth_token="Bearer test",
        )
    )


def test_enable_user_blocked_when_quota_full(monkeypatch):
    # 激活数已达社区版上限（1）：启用禁用用户必须被拒，且不落库。
    with pytest.raises(HTTPException) as exc_info:
        _run(monkeypatch, 2, 1, current_status=0, active_count=COMMUNITY_MAX_ACTIVE_USERS)
    assert exc_info.value.status_code == 400
    assert "激活用户" in str(exc_info.value.detail)
    admin_api.UsersModel.update_status.assert_not_called()


def test_approve_pending_user_blocked_when_quota_full(monkeypatch):
    # 审核通过（2→1）同样占用激活名额。
    with pytest.raises(HTTPException) as exc_info:
        _run(monkeypatch, 3, 1, current_status=2, active_count=COMMUNITY_MAX_ACTIVE_USERS)
    assert exc_info.value.status_code == 400


def test_enable_user_allowed_below_quota(monkeypatch):
    result = _run(
        monkeypatch, 2, 1, current_status=0, active_count=COMMUNITY_MAX_ACTIVE_USERS - 1
    )
    assert result["code"] == 0
    admin_api.UsersModel.update_status.assert_called_once_with(2, 1)


def test_status_change_to_same_active_status_skips_quota(monkeypatch):
    # 已是正常状态（1→1）不新增激活名额，配额满也不拦截。
    result = _run(
        monkeypatch, 2, 1, current_status=1, active_count=COMMUNITY_MAX_ACTIVE_USERS
    )
    assert result["code"] == 0


def test_disable_user_skips_quota(monkeypatch):
    result = _run(monkeypatch, 2, 0, current_status=1, active_count=COMMUNITY_MAX_ACTIVE_USERS)
    assert result["code"] == 0
    admin_api.UsersModel.update_status.assert_called_once_with(2, 0)


def test_invalid_status_value_rejected(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        _run(monkeypatch, 2, 5, current_status=1, active_count=0)
    assert exc_info.value.status_code == 400
    assert "无效的用户状态值" in str(exc_info.value.detail)


def test_admin_cannot_disable_self(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        _run(monkeypatch, 1, 0, current_status=1, active_count=0)
    assert exc_info.value.status_code == 400
    assert "不能禁用自己" in str(exc_info.value.detail)


def test_admin_cannot_set_self_pending(monkeypatch):
    # 待审核账号无法登录（auth_service 拒绝 status=2），管理员把自己置为
    # 待审核将失去重新登录入口，必须拦截。
    with pytest.raises(HTTPException) as exc_info:
        _run(monkeypatch, 1, 2, current_status=1, active_count=0)
    assert exc_info.value.status_code == 400
    assert "待审核" in str(exc_info.value.detail)
    admin_api.UsersModel.update_status.assert_not_called()


# ===== 状态变更的 token 吊销 =====

def test_set_pending_revokes_all_tokens(monkeypatch):
    """1→2 待审核必须与禁用一样吊销全部 token：待审核不占激活名额，
    保留 token 会出现"不占名额但仍可调用接口"的口径漏洞（实测 20260922）"""
    result = _run(monkeypatch, 2, 2, current_status=1, active_count=0)
    assert result["code"] == 0
    admin_api.UserTokensModel.delete_by_user_id.assert_called_once_with(2)


def test_disable_revokes_all_tokens(monkeypatch):
    result = _run(monkeypatch, 2, 0, current_status=1, active_count=0)
    assert result["code"] == 0
    admin_api.UserTokensModel.delete_by_user_id.assert_called_once_with(2)


def test_enable_does_not_revoke_tokens(monkeypatch):
    # 启用/审核通过是放行操作，不应误删 token
    result = _run(monkeypatch, 2, 1, current_status=2, active_count=0)
    assert result["code"] == 0
    admin_api.UserTokensModel.delete_by_user_id.assert_not_called()
