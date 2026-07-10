"""
异步任务配置和媒体常量单元测试

测试 get_async_task_config()、AsyncTaskImplementationId、MediaConstants。
这些是纯配置模块，无需 mock 数据库。
"""
import unittest

from config.unified_config import (
    get_async_task_config,
    AsyncTaskImplementationId,
)
from config.constant import MediaConstants


class TestGetAsyncTaskConfig(unittest.TestCase):
    """测试 get_async_task_config 函数"""

    def test_known_impl_returns_config(self):
        """已知的实现 ID 应返回正确的配置"""
        config = get_async_task_config(AsyncTaskImplementationId.RUNNINGHUB_AUDIO)

        self.assertIsNotNone(config)
        self.assertEqual(config.impl_id, AsyncTaskImplementationId.RUNNINGHUB_AUDIO)
        self.assertEqual(config.name, 'RunningHub音频')

    def test_unknown_impl_returns_default(self):
        """未知的实现 ID 应返回默认的 UNKNOWN 配置"""
        config = get_async_task_config(999)

        self.assertIsNotNone(config)
        self.assertEqual(config.impl_id, 0)
        self.assertEqual(config.name, '未知')
        self.assertFalse(config.need_runninghub_slot)


class TestAsyncTaskConfigValues(unittest.TestCase):
    """测试异步任务配置的具体值"""

    def test_runninghub_audio_config(self):
        """RunningHub 音频配置应为需要槽位且 slot_task_type=1"""
        config = get_async_task_config(AsyncTaskImplementationId.RUNNINGHUB_AUDIO)

        self.assertTrue(config.need_runninghub_slot)
        self.assertEqual(config.slot_task_type, 1)

    def test_runninghub_face_mask_config(self):
        """RunningHub 人脸遮盖配置应为需要槽位且 slot_task_type=2"""
        config = get_async_task_config(AsyncTaskImplementationId.RUNNINGHUB_FACE_MASK)

        self.assertTrue(config.need_runninghub_slot)
        self.assertEqual(config.slot_task_type, 2)

    def test_runninghub_image_face_mask_config(self):
        """RunningHub 图片人脸遮盖配置应为需要槽位且 slot_task_type=3"""
        config = get_async_task_config(AsyncTaskImplementationId.RUNNINGHUB_IMAGE_FACE_MASK)

        self.assertTrue(config.need_runninghub_slot)
        self.assertEqual(config.slot_task_type, 3)

    def test_implementation_id_constants(self):
        """验证实现 ID 常量值"""
        self.assertEqual(AsyncTaskImplementationId.UNKNOWN, 0)
        self.assertEqual(AsyncTaskImplementationId.RUNNINGHUB_AUDIO, 1)
        self.assertEqual(AsyncTaskImplementationId.RUNNINGHUB_FACE_MASK, 2)
        self.assertEqual(AsyncTaskImplementationId.RUNNINGHUB_IMAGE_FACE_MASK, 3)


class TestMediaConstants(unittest.TestCase):
    """测试 MediaConstants 常量"""

    def test_allowed_extensions(self):
        """允许的视频扩展名应包含 .mp4 和 .mov"""
        exts = MediaConstants.ALLOWED_VIDEO_EXTENSIONS
        self.assertIn('.mp4', exts)
        self.assertIn('.mov', exts)
        self.assertIn('.avi', exts)
        self.assertIn('.webm', exts)
        self.assertIn('.mkv', exts)
        self.assertIsInstance(exts, set)

    def test_compress_target_height(self):
        """视频压缩目标分辨率应为 480"""
        self.assertEqual(MediaConstants.VIDEO_COMPRESS_TARGET_HEIGHT, 480)

    def test_compress_threshold_mb(self):
        """视频压缩阈值应为 10 MB"""
        self.assertEqual(MediaConstants.VIDEO_COMPRESS_THRESHOLD_MB, 10)

    def test_reference_video_min_pixel_count(self):
        """参考视频最低总像素数应匹配 Seedance r2v 要求"""
        self.assertEqual(MediaConstants.VIDEO_REFERENCE_MIN_PIXEL_COUNT, 409600)


if __name__ == '__main__':
    unittest.main()
