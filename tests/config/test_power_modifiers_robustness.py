"""上线前鲁棒性：effective_power_modifiers 合并链对异常数据/DB 故障的容错。"""
from unittest.mock import patch

from config.unified_config import (
    TaskTypeId,
    UnifiedConfigRegistry,
    UnifiedTaskConfig,
    TaskCategory,
    PowerModifier,
)

AUTOdl_IMPL = "minimax_h3_first_last_autodl_v1"


def _task():
    return UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO)


def test_impl_not_registered_returns_task_modifiers():
    """implementation 未注册（get_implementation 返回 None）：不炸，返回任务级修饰符"""
    task = _task()
    with patch("config.unified_config.UnifiedConfigRegistry.get_implementation", return_value=None), \
         patch("model.implementation_power.ImplementationPowerModel.get_modifiers", return_value={}):
        merged = {m.attribute: m for m in task.effective_power_modifiers("ghost_impl_v1")}
    assert merged["resolution"].values["480P"] == 0.42  # 任务级原样


def test_impl_config_without_modifiers_field():
    """实现配置无 power_modifiers 属性（旧数据/mock 对象）：不炸"""
    task = _task()
    fake_impl = SimpleNamespace = type("FakeImpl", (), {})()  # 无 power_modifiers 属性
    with patch("config.unified_config.UnifiedConfigRegistry.get_implementation", return_value=fake_impl), \
         patch("model.implementation_power.ImplementationPowerModel.get_modifiers", return_value={}):
        merged = {m.attribute: m for m in task.effective_power_modifiers(AUTOdl_IMPL)}
    assert merged["resolution"].values["480P"] == 0.42


def test_db_modifiers_throws_returns_gracefully():
    """DB 查询抛异常（DB 挂）：吞掉，返回任务级+实现级合并"""
    task = _task()
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers",
               side_effect=RuntimeError("db down")):
        merged = {m.attribute: m for m in task.effective_power_modifiers(AUTOdl_IMPL)}
    assert merged["resolution"].values["480P"] == 0.8   # 实现级仍生效
    assert merged["resolution"].values["720P"] == 1.0


def test_db_spec_garbage_entries_skipped():
    """DB 返回垃圾 spec（非 dict / 非数值 value / 坏 _default）：逐项跳过不炸"""
    task = _task()
    garbage = {
        "resolution": {"480P": "not-a-number", 123: 0.5, "_default": "bad"},  # 480P 值非法、键非 str、default 非法
        "junk_attr": "not-even-a-dict",
    }
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers",
               return_value=garbage):
        merged = {m.attribute: m for m in task.effective_power_modifiers(AUTOdl_IMPL)}
    # 垃圾 480P 被跳过，实现级 0.8 保留；720P 保持 1.0；default 转换失败 → 1.0
    assert merged["resolution"].values["480P"] == 0.8
    assert merged["resolution"].default == 1.0


def test_db_overrides_impl_level_value():
    """DB 合法值覆盖实现级代码默认（运营热更优先级最高）"""
    task = _task()
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers",
               return_value={"resolution": {"480P": 0.9}}):
        merged = {m.attribute: m for m in task.effective_power_modifiers(AUTOdl_IMPL)}
    assert merged["resolution"].values["480P"] == 0.9


def test_get_computing_power_with_garbage_db_modifiers_safe():
    """端到端：垃圾 DB modifiers 下 get_computing_power 正常返回（不炸不返异常）"""
    task = _task()
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers",
               return_value={"resolution": {"480P": None}}), \
         patch("model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
               return_value={}):
        power = task.get_computing_power(
            5, implementation=AUTOdl_IMPL, context={"resolution": "480P"})
    assert isinstance(power, int) and power > 0


def test_unknown_resolution_value_uses_default_multiplier():
    """context 传入修饰符表外的 resolution 值：走 default=1.0，按基准价"""
    import math
    task = _task()
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers", return_value={}), \
         patch("model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
               return_value={}):
        power = task.get_computing_power(
            5, implementation=AUTOdl_IMPL, context={"resolution": "4K"})
    assert power == math.ceil(7 * 1.0) == 7


def test_context_none_still_returns_base_power():
    """context=None：无修饰符乘算，返回基准价"""
    task = _task()
    with patch("model.implementation_power.ImplementationPowerModel.get_modifiers", return_value={}), \
         patch("model.implementation_power.ImplementationPowerModel.get_all_powers_for_implementation",
               return_value={}):
        power = task.get_computing_power(5, implementation=AUTOdl_IMPL)
    assert power == 7
