"""AutoDL 实现级 480P 算力倍率（ImplementationConfig.power_modifiers 覆盖任务级 0.42）。"""
import math
from unittest.mock import patch

from config.unified_config import (
    MINIMAX_H3_AUTODL_480P_PRICE_MULTIPLIER,
    TaskTypeId,
    UnifiedConfigRegistry,
)


def _power(task_type, duration, implementation, resolution):
    task = UnifiedConfigRegistry.get_by_id(task_type)
    with patch(
        "model.implementation_power.ImplementationPowerModel.get_modifiers",
        return_value={},
    ), patch(
        "model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
        return_value={},
    ):
        return task.get_computing_power(
            duration, implementation=implementation,
            context={"resolution": resolution},
        )


def test_autodl_480p_uses_impl_cost_ratio():
    """任务 34 + autodl 实现：5s 480P = ceil(7 × 0.8) = 6（实现级成本比覆盖任务级 0.42）"""
    assert MINIMAX_H3_AUTODL_480P_PRICE_MULTIPLIER == 0.8
    power = _power(
        TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO, 5,
        "minimax_h3_first_last_autodl_v1", "480P")
    assert power == math.ceil(7 * 0.8) == 6


def test_autodl_480p_reference_impl_same_multiplier():
    """任务 37 + autodl 参考生实现同倍率"""
    power = _power(
        TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO, 5,
        "minimax_h3_reference_autodl_v1", "480P")
    assert power == math.ceil(7 * 0.8) == 6


def test_autodl_720p_unchanged():
    """720P 不在实现级修饰符 values 中 → default 1.0：5s = ceil(7 × 1.0) = 7"""
    power = _power(
        TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO, 5,
        "minimax_h3_first_last_autodl_v1", "720P")
    assert power == 7


def test_runninghub_480p_keeps_task_multiplier():
    """RunningHub 实现不受实现级覆盖：5s 480P = ceil(6 × 0.42) = 3（任务级倍率原样）"""
    power = _power(
        TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO, 5,
        "minimax_h3_runninghub_v1", "480P")
    assert power == math.ceil(6 * 0.42) == 3


def test_db_overlay_beats_impl_code_default():
    """DB implementation_power 修饰符优先于实现级代码默认（480P=0.5 → ceil(3.5)=4）"""
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)
    with patch(
        "model.implementation_power.ImplementationPowerModel.get_modifiers",
        return_value={"resolution": {"480P": 0.5}},
    ), patch(
        "model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
        return_value={},
    ):
        power = task.get_computing_power(
            5, implementation="minimax_h3_first_last_autodl_v1",
            context={"resolution": "480P"},
        )
    assert power == math.ceil(7 * 0.5) == 4


def test_effective_modifiers_merge_impl_level():
    """effective_power_modifiers：任务级 0.42 被实现级 480P=0.8 覆盖，720P 键保留"""
    task = UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)
    with patch(
        "model.implementation_power.ImplementationPowerModel.get_modifiers",
        return_value={},
    ):
        merged = {
            m.attribute: m
            for m in task.effective_power_modifiers("minimax_h3_first_last_autodl_v1")
        }
    assert merged["resolution"].values["480P"] == 0.8
    assert merged["resolution"].values["720P"] == 1.0
    # 不传实现：任务级原样（480P=0.42）
    task_only = {
        m.attribute: m
        for m in task.effective_power_modifiers(None)
    }
    assert task_only["resolution"].values["480P"] == 0.42
