"""GET /api/worlds 的 scope=all 门槛单元测试。

背景：独立空间模式（企业版未开启 edition.shared_space）下，
管理员传 scope=all 也必须回退 user 范围，保证用户数据隔离；
仅共享空间模式（社区版 / shared_space=true）下管理员才可看全部用户世界。
"""
import asyncio
from unittest.mock import AsyncMock, patch

import server
from server import get_worlds


def _call(scope, *, isolated, is_admin):
    with patch.object(server, "resolve_authenticated_user_id", new=AsyncMock(return_value=7)), \
         patch("config.constant.Edition.is_space_isolated", return_value=isolated), \
         patch.object(server, "is_admin_user", return_value=is_admin), \
         patch.object(server.UsersModel, "get_display_names", return_value={}), \
         patch.object(server.WorldModel, "list_by_user", return_value={"total": 0, "page": 1, "page_size": 100, "data": []}) as list_mock:
        resp = asyncio.run(get_worlds(scope=scope, visibility='active'))
    assert resp.status_code == 200
    return list_mock


def test_admin_scope_all_isolated_falls_back_to_user():
    list_mock = _call("all", isolated=True, is_admin=True)
    assert list_mock.call_args.kwargs["include_all_users"] is False


def test_admin_scope_all_shared_sees_all_users():
    list_mock = _call("all", isolated=False, is_admin=True)
    assert list_mock.call_args.kwargs["include_all_users"] is True


def test_non_admin_scope_all_shared_falls_back_to_user():
    list_mock = _call("all", isolated=False, is_admin=False)
    assert list_mock.call_args.kwargs["include_all_users"] is False


def test_default_scope_never_sees_all_users():
    list_mock = _call("user", isolated=False, is_admin=True)
    assert list_mock.call_args.kwargs["include_all_users"] is False
