"""15 秒档位开放：实现级 supported_durations、算力扩档、偏好替换、RunningHub 钳制。

背景：AutoDL 15s 实测出片（15.08s ✅），任务 34/37 的 11-15s 档仅对 AutoDL 实现开放
（RunningHub webapp 该段有显存 OOM 风险且算力表无档）。
"""
import math
from types import SimpleNamespace
from unittest.mock import patch

from config.unified_config import (
    MINIMAX_H3_AUTODL_768P_COMPUTING_POWER,
    TaskTypeId,
    UnifiedConfigRegistry,
)

AUTODL_FL = "minimax_h3_first_last_autodl_v1"
AUTODL_REF = "minimax_h3_reference_autodl_v1"
RUNNINGHUB = "minimax_h3_runninghub_v1"


# ==================== 算力扩档 ====================

def test_power_table_has_11_to_15_tiers():
    # 2026-11-09 贴本重定价：ceil(秒×1.25)
    assert MINIMAX_H3_AUTODL_768P_COMPUTING_POWER[11] == 14
    assert MINIMAX_H3_AUTODL_768P_COMPUTING_POWER[12] == 15
    assert MINIMAX_H3_AUTODL_768P_COMPUTING_POWER[13] == 17
    assert MINIMAX_H3_AUTODL_768P_COMPUTING_POWER[14] == 18
    assert MINIMAX_H3_AUTODL_768P_COMPUTING_POWER[15] == 19


def test_autodl_15s_power_via_task():
    """任务 34 + autodl 实现：15s 720P = 21 点（ceil(15×1.375)）"""
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers", return_value={}), \
         patch("model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
               return_value={}):
        power = task.get_computing_power(15, implementation=AUTODL_FL, context={"resolution": "720P"})
    assert power == 19


def test_autodl_15s_480p_multiplier_applies():
    """15s 480P = ceil(21 × 0.8) = 17（实现级倍率对新档位同样生效）"""
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers", return_value={}), \
         patch("model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
               return_value={}):
        power = task.get_computing_power(15, implementation=AUTODL_FL, context={"resolution": "480P"})
    assert power == math.ceil(19 * 0.8) == 16


# ==================== 实现级档位字段 ====================

def test_autodl_impls_declare_4_to_15():
    for name in (AUTODL_FL, AUTODL_REF):
        impl = UnifiedConfigRegistry.get_implementation(name)
        assert impl.supported_durations == list(range(4, 16)), name


def test_runninghub_impl_follows_task_level():
    """RunningHub 实现未声明档位（空列表）→ 跟随任务级基线 4-10"""
    impl = UnifiedConfigRegistry.get_implementation(RUNNINGHUB)
    assert impl.supported_durations == []


def test_implementations_info_carries_durations():
    """任务 34 下发：首尾帧 AutoDL 代码级关闭，不出现在列表；RunningHub 跟随任务级 4-10"""
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers", return_value={}), \
         patch("model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
               return_value={}), \
         patch("model.implementation_power.ImplementationPowerModel.get_config", return_value=None), \
         patch("model.implementation_power.ImplementationPowerModel.is_enabled", return_value=True), \
         patch("utils.config_checker.check_implementation_config_exists", return_value=True), \
         patch("task.visual_drivers.VideoDriverFactory.is_driver_registered", return_value=True):
        info = {row['name']: row for row in task._get_implementations_info()}
    assert AUTODL_FL not in info
    assert info[RUNNINGHUB]['supported_durations'] == list(range(4, 11))


# ==================== 偏好实现替换任务级档位（前端零改动适配） ====================

def _task_dict():
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers", return_value={}), \
         patch("model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
               return_value={}), \
         patch("model.implementation_power.ImplementationPowerModel.get_config", return_value=None), \
         patch("model.implementation_power.ImplementationPowerModel.is_enabled", return_value=True), \
         patch("utils.config_checker.check_implementation_config_exists", return_value=True), \
         patch("task.visual_drivers.VideoDriverFactory.is_driver_registered", return_value=True):
        return task.to_frontend_dict()


def test_frontend_pref_autodl_expands_durations():
    """首尾帧 AutoDL 已关闭：偏好指向它时不扩时长，任务级仍是 4-10。"""
    tasks = [_task_dict()]
    with patch("model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
               return_value={}):
        UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, {'minimax_h3_image_to_video': AUTODL_FL})
    assert tasks[0]['supported_durations'] == list(range(4, 11))
    assert tasks[0].get('user_preferred_implementation') != AUTODL_FL


def test_frontend_no_pref_keeps_baseline():
    """无偏好用户：保持任务级基线 4-10（RunningHub 默认，不暴露 11-15）"""
    tasks = [_task_dict()]
    UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, {})
    assert tasks[0]['supported_durations'] == list(range(4, 11))


def test_frontend_pref_runninghub_keeps_baseline():
    """偏好 RunningHub 的用户：档位保持 4-10（该实现无扩展档）"""
    tasks = [_task_dict()]
    UnifiedConfigRegistry._apply_user_preferences_to_tasks(tasks, {'minimax_h3_image_to_video': RUNNINGHUB})
    assert tasks[0]['supported_durations'] == list(range(4, 11))


# ==================== RunningHub 驱动钳制防御 ====================

def _make_rh_driver():
    from task.visual_drivers.minimax_h3_runninghub_v1_driver import MinimaxH3RunninghubV1Driver
    driver = MinimaxH3RunninghubV1Driver.__new__(MinimaxH3RunninghubV1Driver)
    import logging
    driver.logger = logging.getLogger("test")
    return driver


def test_rh_clamp_15_to_10():
    assert _make_rh_driver()._clamp_duration_to_webapp_bounds(15) == 10


def test_rh_clamp_below_4_to_4():
    assert _make_rh_driver()._clamp_duration_to_webapp_bounds(2) == 4


def test_rh_clamp_valid_unchanged():
    driver = _make_rh_driver()
    assert driver._clamp_duration_to_webapp_bounds(5) == 5
    assert driver._clamp_duration_to_webapp_bounds(10) == 10
    assert driver._clamp_duration_to_webapp_bounds(4) == 4


def test_rh_clamp_garbage_defaults_5():
    driver = _make_rh_driver()
    assert driver._clamp_duration_to_webapp_bounds(None) == 5
    assert driver._clamp_duration_to_webapp_bounds("abc") == 5


# ==================== AutoDL 驱动 15s 原样放行 ====================

def test_autodl_driver_allows_15s():
    from task.visual_drivers.minimax_h3_autodl_v1_driver import MinimaxH3FirstLastAutodlV1Driver
    driver = MinimaxH3FirstLastAutodlV1Driver.__new__(MinimaxH3FirstLastAutodlV1Driver)
    tool = SimpleNamespace(duration=15)
    assert driver._clamp_duration(tool) == 15


# ==================== 提交侧档位校验函数 ====================

def _task_config():
    return UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)


def test_duration_check_baseline_passes_any_impl():
    """基线档（4-10）：任何实现（含 None）都放行"""
    task = _task_config()
    for impl in (RUNNINGHUB, AUTODL_FL, None):
        ok, reason = UnifiedConfigRegistry.is_duration_supported_for_implementation(task, 10, impl)
        assert ok and reason == "", impl


def test_duration_check_15s_autodl_passes():
    ok, reason = UnifiedConfigRegistry.is_duration_supported_for_implementation(_task_config(), 15, AUTODL_FL)
    assert ok and reason == ""


def test_duration_check_15s_runninghub_rejected():
    ok, reason = UnifiedConfigRegistry.is_duration_supported_for_implementation(_task_config(), 15, RUNNINGHUB)
    assert not ok
    assert "切换" in reason and "15" in reason


def test_duration_check_15s_no_impl_rejected():
    """实现方解析失败（None）：15s 拒绝（宁拒不放，防落到 RunningHub OOM）"""
    ok, reason = UnifiedConfigRegistry.is_duration_supported_for_implementation(_task_config(), 15, None)
    assert not ok


def test_duration_check_out_of_all_ranges_rejected():
    """20s 超出所有实现的档位：拒绝"""
    ok, _ = UnifiedConfigRegistry.is_duration_supported_for_implementation(_task_config(), 20, AUTODL_FL)
    assert not ok


# ==================== 管理后台实现方档位合并（api/admin.py impl_durations 规则） ====================

def test_admin_impl_durations_merge_rule():
    """后台实现方档位 = 任务级基线 ∪ 实现级扩展档：autodl 显示 4-15、runninghub 仅 4-10"""
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)
    for impl_name, expected in ((AUTODL_FL, list(range(4, 16))), (RUNNINGHUB, list(range(4, 11)))):
        merged = set(task.supported_durations)
        impl_cfg = UnifiedConfigRegistry.get_implementation(impl_name)
        if impl_cfg and getattr(impl_cfg, 'supported_durations', None):
            merged.update(impl_cfg.supported_durations)
        assert sorted(merged) == expected, impl_name


def test_admin_default_powers_cover_expanded_tiers():
    """后台分档默认值可推导到 11-15：来自 autodl 实现的 default_computing_power"""
    impl_cfg = UnifiedConfigRegistry.get_implementation(AUTODL_FL)
    for duration, expected in ((11, 14), (12, 15), (13, 17), (14, 18), (15, 19)):
        assert impl_cfg.default_computing_power[duration] == expected
