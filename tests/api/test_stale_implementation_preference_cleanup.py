"""GET /implementation-preferences 失效偏好自愈：偏好指向的实现方停用/未配置时清除固定标记。

背景事故：用户固定 huimengi 后供应商停用，任务持续失败
（FIXED_IMPLEMENTATION_UNAVAILABLE），且设置界面因可用列表过滤掉该供应商
而无法取消固定。修复：接口返回前清除指向不可用实现方的偏好并写库。
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import enterprise.routes.user as enterprise_user


HUIMENGI = "seedance_2_0_mini_huimengi_v1"
TOPENROUTER = "seedance_2_0_mini_topenrouter_v1"
TASK_KEY = "seedance_2_0_mini_image_to_video"


def _task_config():
    return SimpleNamespace(
        key=TASK_KEY,
        name="Seedance 2.0 Mini 图生视频",
        id=104,
        driver_name=TASK_KEY,
        category=None,
        categories=[],
        implementations=[HUIMENGI, TOPENROUTER],
    )


def _impl_config(name):
    return SimpleNamespace(
        display_name=name,
        site_number=None,
        default_computing_power={5: 100},
        is_enabled=lambda _driver_name: True,
    )


def _impl_config_exists(name):
    # 模拟 huimengi 未配置（api_key 缺失）、topenrouter 已配置
    return name == TOPENROUTER


def _patch_common(cleared):
    def fake_clear(user_id, task_key):
        cleared.append((user_id, task_key))
        return 1

    ctx = patch(
        "enterprise.routes.user.UnifiedConfigRegistry.get_all",
        return_value=[_task_config()],
    ), patch(
        "enterprise.routes.user.UnifiedConfigRegistry.get_implementation",
        side_effect=lambda name: _impl_config(name),
    ), patch(
        "enterprise.routes.user.check_implementation_config_exists",
        side_effect=_impl_config_exists,
    ), patch(
        "enterprise.routes.user.ImplementationStatsCacheModel.get_by_days",
        return_value=[],
    ), patch(
        "enterprise.routes.user.ImplementationPowerModel.get_config",
        return_value={},
    ), patch(
        "enterprise.routes.user.ImplementationPowerModel.get_all_powers_for_implementation",
        return_value={},
    ), patch(
        "enterprise.routes.user.get_implementation_id",
        return_value=104,
    ), patch(
        "enterprise.routes.user.UserTokensModel.get_user_id_by_token",
        return_value=1,
    ), patch(
        "enterprise.routes.user.UsersModel.get_by_id",
        return_value=SimpleNamespace(id=1),
    ), patch(
        "enterprise.routes.user.UsersModel.clear_implementation_preference",
        side_effect=fake_clear,
    )
    return ctx


def _run(prefs, locks, cleared):
    ctxs = _patch_common(cleared)
    with ctxs[0], ctxs[1], ctxs[2], ctxs[3], ctxs[4], ctxs[5], ctxs[6], ctxs[7], ctxs[8], ctxs[9], \
            patch("enterprise.routes.user.UsersModel.get_all_preferences", return_value=dict(prefs)), \
            patch("enterprise.routes.user.UsersModel.get_all_locks", return_value=dict(locks)), \
            patch("enterprise.routes.user.IS_COMMUNITY_EDITION", False):
        return asyncio.run(enterprise_user.get_implementation_preferences("Bearer token"))


def test_stale_preference_pointing_to_unconfigured_impl_is_cleared():
    """偏好固定在未配置的 huimengi：清除偏好与固定标记，返回值不再包含。"""
    cleared = []
    result = _run({TASK_KEY: HUIMENGI}, {TASK_KEY: True}, cleared)

    assert cleared == [(1, TASK_KEY)]
    assert result["data"]["preferences"] == {}
    assert result["data"]["locks"] == {}


def test_valid_preference_survives():
    """偏好指向已配置的 topenrouter：不清除。"""
    cleared = []
    result = _run({TASK_KEY: TOPENROUTER}, {TASK_KEY: True}, cleared)

    assert cleared == []
    assert result["data"]["preferences"] == {TASK_KEY: TOPENROUTER}
    assert result["data"]["locks"] == {TASK_KEY: True}


def test_preference_survives_when_only_one_impl_available():
    """任务仅剩 1 个可用实现方时不进 available_implementations（len>1 才纳入），
    但指向该实现方的偏好仍有效，不得误清。"""
    cleared = []
    # topenrouter 已配置；再把 topenrouter 从任务定义里拿掉一个的极端情形由
    # enabled_by_task 覆盖：这里直接验证 available_implementations 为空时偏好保留
    result = _run({TASK_KEY: TOPENROUTER}, {}, cleared)

    assert cleared == []
    assert result["data"]["preferences"] == {TASK_KEY: TOPENROUTER}
    # 仅 1 个可用实现方：不进可选列表，但 enabled_by_task 已兜住判定
    assert TASK_KEY not in result["data"]["available_implementations"]


def test_unknown_task_preference_is_cleared():
    """偏好指向的任务已从配置下线（enabled_by_task 无记录）：清除。"""
    cleared = []
    result = _run({"legacy_task": "legacy_impl_v1"}, {"legacy_task": True}, cleared)

    assert cleared == [(1, "legacy_task")]
    assert result["data"]["preferences"] == {}
    assert result["data"]["locks"] == {}
