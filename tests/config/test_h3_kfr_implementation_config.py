"""
H3 首帧参考混合实现方挂进类型 37 参考生的配置层测试

背景（docs/video/h3_keyframe_ref_as_reference_impl_design.md）：
- 旧路线（be243a94）：参考生点名首帧时把 task_type 改成隐藏任务 50（minimax_h3_kfr），
  用户供应商偏好按任务键保存，导致排不开也切不走。
- 新路线：任务始终类型 37，minimax_h3_keyframe_ref_runninghub_v1 挂进类型 37 的
  implementations 与参考生并列；类型 50 代码级硬禁用（enabled=False）只留历史收尾。
"""
import unittest

from config import constant
from config.unified_config import (
    DriverImplementation,
    DriverKey,
    TaskTypeId,
    UnifiedConfigRegistry,
    init_unified_config,
)

KFR_IMPL = DriverImplementation.MINIMAX_H3_KEYFRAME_REF_RUNNINGHUB_V1
RH_REF_IMPL = DriverImplementation.MINIMAX_H3_REFERENCE_RUNNINGHUB_V1
AUTODL_REF_IMPL = DriverImplementation.MINIMAX_H3_REFERENCE_AUTODL_V1


class TestH3KeyframeRefAsImplementation(unittest.TestCase):
    """类型 37 挂载 KFR 实现方 + 类型 50 硬禁用的配置断言"""

    def setUp(self):
        self._registry_snapshot = UnifiedConfigRegistry.snapshot()
        UnifiedConfigRegistry.restore()
        init_unified_config()

    def tearDown(self):
        UnifiedConfigRegistry.restore(getattr(self, "_registry_snapshot", None))

    def test_reference_task_includes_keyframe_ref_implementation(self):
        """类型 37 implementations 含 KFR，且顺序与 sort_order 一致（KFR 最前）"""
        config = UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_REFERENCE_TO_VIDEO)
        self.assertEqual(
            config.implementations,
            [KFR_IMPL, RH_REF_IMPL, AUTODL_REF_IMPL],
        )
        # 任务默认实现方仍是 RunningHub 参考生（未点名时的兜底）
        self.assertEqual(config.implementation, RH_REF_IMPL)

    def test_keyframe_ref_implementation_sorts_before_reference_impls(self):
        """KFR sort=5204 排在 RH 参考生（5205）/ AutoDL 参考生（5208）之前"""
        registry = UnifiedConfigRegistry
        kfr = registry.get_implementation(KFR_IMPL)
        rh = registry.get_implementation(RH_REF_IMPL)
        autodl = registry.get_implementation(AUTODL_REF_IMPL)
        self.assertLess(kfr.sort_order, rh.sort_order)
        self.assertLess(rh.sort_order, autodl.sort_order)

    def test_keyframe_ref_display_name_distinguished(self):
        """KFR 显示名带「首帧参考」，不再与普通 RunningHub 参考生同名"""
        kfr = UnifiedConfigRegistry.get_implementation(KFR_IMPL)
        self.assertIn('首帧参考', kfr.display_name)
        self.assertTrue(kfr.enabled)

    def test_task50_hard_disabled_but_kept_for_legacy_rows(self):
        """类型 50：hidden + enabled=False（拒绝新创建），配置/实现方保留供在途行找驱动"""
        config = UnifiedConfigRegistry.get_by_id(TaskTypeId.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO)
        self.assertTrue(config.hidden)
        self.assertFalse(config.enabled)
        # 实现方本身保留启用：在途 type=50 行按 implementation=100 建驱动不受影响
        self.assertTrue(UnifiedConfigRegistry.get_implementation(KFR_IMPL).enabled)

    def test_driver_implementation_mapping_updated(self):
        """映射表：类型 37 列表含 KFR；类型 50 不挂映射条目（避免实现方管理页
        渲染出冗余的 minimax_h3_keyframe_ref_to_video 分组，历史行找驱动走
        create_driver_by_implementation 按实现方名解析，不依赖映射）"""
        ref_mapping = constant.DRIVER_IMPLEMENTATION_MAPPING[DriverKey.MINIMAX_H3_REFERENCE_TO_VIDEO]
        self.assertIn(KFR_IMPL, ref_mapping)
        self.assertNotIn(DriverKey.MINIMAX_H3_KEYFRAME_REF_TO_VIDEO, constant.DRIVER_IMPLEMENTATION_MAPPING)

    def test_route_flag_removed(self):
        """旧路由开关 H3_KEYFRAME_REF_ROUTE_ENABLED 已删除（前后端不再各自镜像常量）"""
        self.assertFalse(hasattr(constant, 'H3_KEYFRAME_REF_ROUTE_ENABLED'))


if __name__ == '__main__':
    unittest.main()
