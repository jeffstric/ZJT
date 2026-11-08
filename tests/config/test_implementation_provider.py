"""
实现方级供应商判定单元测试

背景（事故 ai_tools 13439/13440）：AutoDL 实现方挂在 RunningHub 任务类型（34/37）下，
运行时按任务类型 provider 误判为 RunningHub，提交前被注入 RunningHub 池密钥覆盖
autodl token，上游返回 401。修复后供应商判定一律按实现方级 provider
（ImplementationConfig.provider，未标注时继承任务类型 provider）。
"""
import unittest

from config.unified_config import (
    TaskProvider,
    TaskTypeId,
    UnifiedConfigRegistry,
    init_unified_config,
    is_runninghub_implementation,
    is_runninghub_task,
)


class _FakeAITool:
    """鸭子类型 ai_tool（只需 type / implementation）"""

    def __init__(self, type_, implementation=None):
        self.type = type_
        self.implementation = implementation


class TestGetImplementationProvider(unittest.TestCase):
    """UnifiedConfigRegistry.get_implementation_provider 测试"""

    def setUp(self):
        self._registry_snapshot = UnifiedConfigRegistry.snapshot()
        UnifiedConfigRegistry.restore()
        init_unified_config()

    def tearDown(self):
        UnifiedConfigRegistry.restore(getattr(self, "_registry_snapshot", None))

    def test_autodl_implementation_explicit_provider(self):
        """跨供应商挂载的 AutoDL 实现方显式标注 autodl"""
        for name in ('minimax_h3_reference_autodl_v1', 'minimax_h3_first_last_autodl_v1'):
            self.assertEqual(
                UnifiedConfigRegistry.get_implementation_provider(name),
                TaskProvider.AUTODL,
                f"{name} 应标注为 autodl 供应商",
            )

    def test_runninghub_implementation_inherits_task_provider(self):
        """未标注 provider 的 RunningHub 实现方继承任务类型 provider"""
        self.assertEqual(
            UnifiedConfigRegistry.get_implementation_provider('minimax_h3_runninghub_v1'),
            TaskProvider.RUNNINGHUB,
        )

    def test_unknown_implementation_returns_none(self):
        """未注册实现方返回 None"""
        self.assertIsNone(UnifiedConfigRegistry.get_implementation_provider('not_exist_v1'))


class TestIsRunninghubImplementation(unittest.TestCase):
    """is_runninghub_implementation 测试"""

    def test_autodl_by_id_and_name(self):
        """AutoDL 实现方（ID 108/109 与名称）不是 RunningHub——401 事故回归"""
        from config.unified_config import DriverImplementationId
        self.assertFalse(is_runninghub_implementation(DriverImplementationId.MINIMAX_H3_REFERENCE_AUTODL_V1))
        self.assertFalse(is_runninghub_implementation(DriverImplementationId.MINIMAX_H3_FIRST_LAST_AUTODL_V1))
        self.assertFalse(is_runninghub_implementation('minimax_h3_reference_autodl_v1'))
        self.assertFalse(is_runninghub_implementation('minimax_h3_first_last_autodl_v1'))

    def test_runninghub_by_name(self):
        """RunningHub 实现方（继承任务类型 provider）判定为 True"""
        self.assertTrue(is_runninghub_implementation('minimax_h3_runninghub_v1'))
        self.assertTrue(is_runninghub_implementation('minimax_h3_turbo_runninghub_v1'))

    def test_non_runninghub_provider_task_type(self):
        """非 RunningHub 供应商任务类型下的实现方判定为 False"""
        self.assertFalse(is_runninghub_implementation('sora2_duomi_v1'))

    def test_unknown_id_returns_false(self):
        """未知实现方 ID 判定为 False（不注入池密钥，宁缺勿错）"""
        self.assertFalse(is_runninghub_implementation(999999))

    def test_user_module_prefix_returns_false(self):
        """用户模块动态实现方豁免（原 visual_task 前缀特判收编）"""
        self.assertFalse(is_runninghub_implementation('user_module:custom_impl_v1'))

    def test_empty_and_none(self):
        """空值判定为 False"""
        self.assertFalse(is_runninghub_implementation(None))
        self.assertFalse(is_runninghub_implementation(''))
        self.assertFalse(is_runninghub_implementation(0))


class TestIsRunninghubTask(unittest.TestCase):
    """is_runninghub_task 测试"""

    def setUp(self):
        self._registry_snapshot = UnifiedConfigRegistry.snapshot()
        UnifiedConfigRegistry.restore()
        init_unified_config()

    def tearDown(self):
        UnifiedConfigRegistry.restore(getattr(self, "_registry_snapshot", None))

    def test_autodl_implementation_recorded(self):
        """记录了 AutoDL 实现方的 H3 任务不是 RunningHub 任务——401 事故回归"""
        self.assertFalse(is_runninghub_task(_FakeAITool(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO, 109)))
        self.assertFalse(is_runninghub_task(_FakeAITool(TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO, 108)))

    def test_runninghub_implementation_recorded(self):
        """记录了 RunningHub 实现方的 H3 任务是 RunningHub 任务"""
        self.assertTrue(is_runninghub_task(_FakeAITool(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO, 65)))

    def test_impl_name_override_wins(self):
        """impl_name（真实执行驱动）优先于 ai_tool.implementation 记录值"""
        tool = _FakeAITool(TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO, 108)
        self.assertTrue(is_runninghub_task(tool, 'minimax_h3_reference_runninghub_v1'))
        tool_rh = _FakeAITool(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO, 65)
        self.assertFalse(is_runninghub_task(tool_rh, 'minimax_h3_first_last_autodl_v1'))

    def test_unrecorded_impl_falls_back_to_task_type(self):
        """实现方未记录时回退任务类型 provider（入队预占槽位场景）"""
        self.assertTrue(is_runninghub_task(_FakeAITool(TaskTypeId.MINIMAX_H3_IMAGE_TO_VIDEO, None)))
        self.assertFalse(is_runninghub_task(_FakeAITool(TaskTypeId.SORA2_IMAGE_TO_VIDEO, None)))


if __name__ == '__main__':
    unittest.main()
