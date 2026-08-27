"""
视频分辨率校验工具测试
"""
import unittest


class TestValidateVideoResolution(unittest.TestCase):
    def setUp(self):
        from config.unified_config import ImplementationConfig, UnifiedConfigRegistry

        self._registry_snapshot = UnifiedConfigRegistry.snapshot()
        UnifiedConfigRegistry._implementations.clear()
        UnifiedConfigRegistry.register_implementation(
            ImplementationConfig(
                name='test_video_impl',
                display_name='测试视频实现',
                driver_class='TestDriver',
                supported_video_resolutions=[
                    {'value': '720P', 'label': '720P', 'driver_value': '720P'},
                    {'value': '1080P', 'label': '1080P', 'driver_value': '1080P'},
                ],
                default_video_resolution='720P',
            )
        )
        UnifiedConfigRegistry.register_implementation(
            ImplementationConfig(
                name='test_plain_impl',
                display_name='普通实现',
                driver_class='PlainDriver',
            )
        )

    def tearDown(self):
        from config.unified_config import UnifiedConfigRegistry

        # 恢复注册表快照，避免测试实现方残留污染同进程后续测试
        UnifiedConfigRegistry.restore(self._registry_snapshot)

    def test_missing_resolution_uses_implementation_default(self):
        from utils.video_resolution import validate_video_resolution

        self.assertEqual(validate_video_resolution(None, 'test_video_impl'), '720P')

    def test_valid_resolution_kept(self):
        from utils.video_resolution import validate_video_resolution

        self.assertEqual(validate_video_resolution('1080P', 'test_video_impl'), '1080P')

    def test_invalid_resolution_falls_back_to_default(self):
        from utils.video_resolution import validate_video_resolution

        self.assertEqual(validate_video_resolution('4K', 'test_video_impl'), '720P')

    def test_unsupported_implementation_returns_none(self):
        from utils.video_resolution import validate_video_resolution

        self.assertIsNone(validate_video_resolution('1080P', 'test_plain_impl'))


if __name__ == '__main__':
    unittest.main()
