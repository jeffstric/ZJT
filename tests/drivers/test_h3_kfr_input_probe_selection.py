"""
H3 首帧参考混合实现方的输入兼容探测与实现方选择测试

覆盖 docs/video/h3_keyframe_ref_as_reference_impl_design.md §1 的四条验收路径
（工厂层部分）与 KFR 驱动 validate_input_compatibility 钩子契约：

1. 点名首帧 + 无偏好 → 选 KFR（sort 最前且兼容）
2. 无点名 + 无偏好 → 跳过 KFR，选普通参考生
3. 点名首帧 + 固定 AutoDL → 偏好优先，走 AutoDL
4. 固定 KFR + 无点名 → 固定语义失败（不清青换供应商），并清偏好
5. input_probe=None → 不探测，行为与旧版一致（其他任务不受影响）
"""
import json
import logging
import unittest
from unittest.mock import patch

from config.unified_config import (
    ImplementationConfig,
    TaskCategory,
    TaskProvider,
    UnifiedTaskConfig,
    UnifiedConfigRegistry,
)
from task.visual_drivers.base_video_driver import BaseVideoDriver, DriverInputProbe
from task.visual_drivers.driver_factory import VideoDriverFactory
from task.visual_drivers.minimax_h3_keyframe_ref_runninghub_v1_driver import (
    MinimaxH3KeyframeRefRunninghubV1Driver,
)


def make_keyframe_ref_driver():
    """绕过 __init__（避免 runninghub.api_key 配置依赖），钩子只用到基类解析方法"""
    driver = MinimaxH3KeyframeRefRunninghubV1Driver.__new__(MinimaxH3KeyframeRefRunninghubV1Driver)
    driver.logger = logging.getLogger("test-kfr")
    return driver


def make_orm_like_tool(prompt="", image_mode="multi_reference", reference_images=None, **overrides):
    """与 AIToolsModel 同形态的鸭子对象（image_mode 存 extra_config JSON）"""
    base = {
        "prompt": prompt,
        "extra_config": json.dumps({"image_mode": image_mode}) if image_mode else None,
        "reference_images": json.dumps(reference_images) if reference_images else None,
        "image_path": None,
        "audio_path": None,
        "video_path": None,
    }
    base.update(overrides)
    return type("FakeAITool", (), base)()


class KeyframeRefCompatDriver(BaseVideoDriver):
    """复用 KFR 驱动真实钩子逻辑的可注册测试驱动（零复制，直接绑方法对象）"""

    def __init__(self, **kwargs):
        super().__init__(driver_name="test_kfr_probe_driver", driver_type=999)

    def build_create_request(self, ai_tool):
        return {}

    def build_check_query(self, project_id):
        return {}

    def submit_task(self, ai_tool):
        return {"success": True, "project_id": "mock_123"}

    def check_status(self, project_id):
        return {"status": "RUNNING"}

    validate_input_compatibility = MinimaxH3KeyframeRefRunninghubV1Driver.validate_input_compatibility


class PlainDriver(BaseVideoDriver):
    """无兼容约束的普通实现方（基类默认恒兼容的替身）"""

    def __init__(self, **kwargs):
        super().__init__(driver_name="test_plain_driver", driver_type=999)

    def build_create_request(self, ai_tool):
        return {}

    def build_check_query(self, project_id):
        return {}

    def submit_task(self, ai_tool):
        return {"success": True, "project_id": "mock_123"}

    def check_status(self, project_id):
        return {"status": "RUNNING"}


class TestKeyframeRefDriverHook(unittest.TestCase):
    """KFR 驱动 validate_input_compatibility 契约"""

    def test_mentioned_first_frame_compatible(self):
        driver = make_keyframe_ref_driver()
        ok, reason = driver.validate_input_compatibility(make_orm_like_tool(
            prompt="图1是首帧。角色走进厨房。",
            reference_images=["a.png", "b.png"],
        ))
        self.assertTrue(ok)
        self.assertIsNone(reason)

    def test_mentioned_last_frame_compatible(self):
        driver = make_keyframe_ref_driver()
        ok, _ = driver.validate_input_compatibility(make_orm_like_tool(
            prompt="镜头推进。图3是尾帧。",
            reference_images=["a.png", "b.png", "c.png"],
        ))
        self.assertTrue(ok)

    def test_no_mention_incompatible(self):
        driver = make_keyframe_ref_driver()
        ok, reason = driver.validate_input_compatibility(make_orm_like_tool(
            prompt="角色在跳舞，两个人对视。",
            reference_images=["a.png"],
        ))
        self.assertFalse(ok)
        self.assertIn("未点名", reason)

    def test_first_last_frame_mode_incompatible(self):
        driver = make_keyframe_ref_driver()
        ok, reason = driver.validate_input_compatibility(make_orm_like_tool(
            prompt="图1是首帧。",
            image_mode="first_last_frame",
            reference_images=["a.png"],
        ))
        self.assertFalse(ok)
        self.assertIn("参考模式", reason)

    def test_no_reference_images_incompatible(self):
        driver = make_keyframe_ref_driver()
        ok, reason = driver.validate_input_compatibility(make_orm_like_tool(
            prompt="图1是首帧。",
            reference_images=None,
        ))
        self.assertFalse(ok)
        self.assertIn("参考图", reason)

    def test_probe_object_same_verdict_as_orm_row(self):
        """DriverInputProbe 与 ORM 形态对象判定一致（钩子代码通用性）"""
        driver = make_keyframe_ref_driver()
        probe = DriverInputProbe(
            prompt="图1是首帧。",
            extra_config=DriverInputProbe.build_extra_config("multi_reference"),
            reference_images=json.dumps(["a.png"]),
        )
        ok_probe, _ = driver.validate_input_compatibility(probe)
        ok_orm, _ = driver.validate_input_compatibility(make_orm_like_tool(
            prompt="图1是首帧。", reference_images=["a.png"],
        ))
        self.assertEqual(ok_probe, ok_orm)
        self.assertTrue(ok_probe)


class TestProbedImplementationSelection(unittest.TestCase):
    """工厂三层选择接入 input_probe 的验收路径"""

    TASK_TYPE_ID = 9102
    KFR = "test_kfr_impl"
    RH = "test_rh_ref_impl"
    AUTODL = "test_autodl_ref_impl"

    def setUp(self):
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory._last_create_error = None
        self._original_configs = UnifiedConfigRegistry._configs.copy()
        self._original_id_map = UnifiedConfigRegistry._id_map.copy()
        self._original_implementations = UnifiedConfigRegistry._implementations.copy()

        for impl_name, driver_cls, sort_order in [
            (self.KFR, KeyframeRefCompatDriver, 100),
            (self.RH, PlainDriver, 200),
            (self.AUTODL, PlainDriver, 300),
        ]:
            VideoDriverFactory.register_driver(impl_name, driver_cls)
            UnifiedConfigRegistry.register_implementation(ImplementationConfig(
                name=impl_name,
                display_name=impl_name,
                driver_class=impl_name,
                sort_order=sort_order,
            ))

        # 模拟类型 37 的实现方挂载：KFR 排最前，默认实现方是普通参考生
        config = UnifiedTaskConfig(
            id=self.TASK_TYPE_ID,
            key='test_probed_selection_task',
            name='Test Probed Selection',
            category=TaskCategory.IMAGE_TO_VIDEO,
            provider=TaskProvider.RUNNINGHUB,
            driver_name='test_probed_driver_key',
            implementation=self.RH,
            implementations=[self.KFR, self.RH, self.AUTODL],
            computing_power=1,
        )
        UnifiedConfigRegistry._configs[config.key] = config
        UnifiedConfigRegistry._id_map[config.id] = config.key
        self.config = config

        # 用户偏好 mock（_get_implementation_for_user 函数体内 import，patch 源模块）
        self._pref_patcher = patch("model.users.UsersModel")
        self.users_model = self._pref_patcher.start()
        self.users_model.get_implementation_preference.return_value = None
        self.users_model.is_implementation_locked.return_value = False

        # 管理页算力配置 DB mock（本机无 MySQL 时 execute_query 会阻塞挂死；
        # 走内存 fallback：默认启用 + 代码默认 sort/算力表）
        self._power_patcher = patch("model.implementation_power.ImplementationPowerModel")
        power_model = self._power_patcher.start()
        power_model.get_config.return_value = None
        power_model.is_enabled.return_value = True
        power_model.get_all_powers_for_implementation.return_value = {}

    def tearDown(self):
        VideoDriverFactory._registered_drivers.clear()
        VideoDriverFactory._last_create_error = None
        UnifiedConfigRegistry._configs = self._original_configs
        UnifiedConfigRegistry._id_map = self._original_id_map
        UnifiedConfigRegistry._implementations = self._original_implementations
        self._pref_patcher.stop()
        self._power_patcher.stop()

    def _probe(self, prompt, image_mode="multi_reference", urls=None):
        return DriverInputProbe(
            prompt=prompt,
            extra_config=DriverInputProbe.build_extra_config(image_mode),
            reference_images=json.dumps(urls or ["a.png", "b.png"]),
        )

    def test_mention_no_pref_selects_keyframe_ref(self):
        """验收 2：点名首帧 + 无偏好 → KFR（sort 最前且兼容）"""
        impl, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=None, config=self.config,
            input_probe=self._probe("图1是首帧。角色进门。"),
        )
        self.assertEqual(impl, self.KFR)

    def test_no_mention_no_pref_skips_keyframe_ref(self):
        """验收 3：无点名 → KFR 不兼容被跳过 → 普通参考生"""
        impl, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=None, config=self.config,
            input_probe=self._probe("角色在跳舞。"),
        )
        self.assertEqual(impl, self.RH)

    def test_mention_prefers_fixed_autodl(self):
        """验收 1：点名首帧 + 偏好 AutoDL（未锁定）→ 走 AutoDL（兼容，偏好优先）"""
        self.users_model.get_implementation_preference.return_value = self.AUTODL
        impl, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=1, config=self.config,
            input_probe=self._probe("图1是首帧。"),
        )
        self.assertEqual(impl, self.AUTODL)

    def test_fixed_keyframe_ref_without_mention_fails(self):
        """验收 4：固定 KFR + 无点名 → 固定语义失败 + 清偏好（不静默换供应商）"""
        self.users_model.get_implementation_preference.return_value = self.KFR
        self.users_model.is_implementation_locked.return_value = True
        impl, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=1, config=self.config,
            input_probe=self._probe("角色在跳舞。"),
        )
        self.assertIsNone(impl)
        self.assertEqual(
            VideoDriverFactory._last_create_error.get("reason"),
            "FIXED_IMPLEMENTATION_UNAVAILABLE",
        )
        self.assertIn("首帧", VideoDriverFactory._last_create_error.get("message", ""))
        self.users_model.clear_implementation_preference.assert_called_once()

    def test_unlocked_keyframe_ref_pref_without_mention_falls_back(self):
        """未锁定的 KFR 偏好 + 无点名 → warning 后自动选（落到普通参考生）"""
        self.users_model.get_implementation_preference.return_value = self.KFR
        impl, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=1, config=self.config,
            input_probe=self._probe("角色在跳舞。"),
        )
        self.assertEqual(impl, self.RH)

    def test_no_probe_keeps_legacy_behaviour(self):
        """probe=None：不探测，KFR 排最前直接选中（其他任务类型调用方零影响）"""
        impl, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=None, config=self.config,
        )
        self.assertEqual(impl, self.KFR)

    def test_all_incompatible_reports_no_implementation(self):
        """全部候选不兼容（非参考模式探测）→ NO_IMPLEMENTATION_AVAILABLE"""
        impl, _ = VideoDriverFactory._get_implementation_for_user(
            self.TASK_TYPE_ID, user_id=None, config=self.config,
            input_probe=self._probe("图1是首帧。", image_mode="first_last_frame"),
        )
        # KFR 不兼容；RH/AutoDL 无钩子恒兼容 → 仍可选 RH
        self.assertEqual(impl, self.RH)


if __name__ == "__main__":
    unittest.main()
