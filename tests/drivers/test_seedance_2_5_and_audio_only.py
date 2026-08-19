"""
Seedance 2.5 驱动 + 纯音频输入路由 单元测试
纯单元测试，不依赖数据库，使用 mock 替代所有外部依赖

测试覆盖：
- Seedance 2.5 子类实例化（model_name / driver_type / impl_name）
- Seedance 2.5 build_create_request：
    * 多参考图 + 参考音频（镜像官方 curl 示例，校验 model 名下发）
    * 纯音频输入（无图无视频，仅参考音频）→ content 含 reference_audio
- 纯音频路由兜底（volcengine 驱动）：
    * 无 image_mode 提示 + 仅有音频 → 自动改判 multi_reference，content 含 reference_audio
    * image_mode=first_last_frame + 仅有音频（CLI/非 server 入口）→ 同样改判
"""
import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# 必须在导入会触发 model/database 的模块前，给 config_unit.yml 塞进一个最小配置缓存。
os.environ.setdefault("comfyui_env", "unit")
from config import config_util  # noqa: E402

config_util._config_cache["config_unit.yml"] = {
    "database": {"host": "localhost", "port": 3306, "user": "root",
                 "password": "", "database": "unit"},
    "server": {}, "file_storage": {},
}

# Mock 外部依赖（必须在 import driver 之前）
sys.modules['utils.sentry_util'] = MagicMock()
sys.modules['utils.image_upload_utils'] = MagicMock()


def _create_volcengine_driver(driver_type=23, model_name='doubao-seedance-2-0-260128',
                              api_key='test_api_key'):
    """创建 SeedanceVolcengineV1Driver（含 2.5 子类）实例"""
    from task.visual_drivers.seedance_volcengine_v1_driver import SeedanceVolcengineV1Driver

    with patch('task.visual_drivers.seedance_volcengine_v1_driver.get_dynamic_config_value') as mock_config, \
         patch('task.visual_drivers.seedance_volcengine_v1_driver.get_config', return_value={}):

        def side_effect(*keys, default=None):
            key_map = {
                ('volcengine', 'api_key'): api_key,
                ('timeout', 'request_timeout'): 30,
                ('server', 'is_local'): False,
                ('test_mode', 'enabled'): False,
                ('test_mode', 'mock_videos'): {},
            }
            return key_map.get(keys, default)

        mock_config.side_effect = side_effect
        return SeedanceVolcengineV1Driver(driver_type=driver_type, model_name=model_name)


def _create_2_5_driver():
    """创建 Seedance 2.5 子类实例"""
    from config.unified_config import TaskTypeId, DriverImplementation
    return _create_volcengine_driver(
        driver_type=TaskTypeId.SEEDANCE_2_5_IMAGE_TO_VIDEO,
        model_name='doubao-seedance-2-5-260628',
    )


def _make_ai_tool(prompt='测试提示词', image_path=None, extra_config=None,
                  duration=5, reference_images=None, audio_path=None,
                  video_path=None, ratio=None):
    """创建模拟的 ai_tool 对象"""
    tool = MagicMock()
    tool.id = 3001
    tool.prompt = prompt
    tool.image_path = image_path
    tool.extra_config = extra_config
    tool.duration = duration
    tool.reference_images = reference_images
    tool.audio_path = audio_path
    tool.video_path = video_path
    tool.ratio = ratio
    return tool


class TestSeedance25Driver(unittest.TestCase):
    """Seedance 2.5 子类实例化"""

    def test_seedance_2_5_driver_instantiation(self):
        from task.visual_drivers.seedance_volcengine_v1_driver import Seedance25VolcengineV1Driver
        from config.unified_config import TaskTypeId

        with patch('task.visual_drivers.seedance_volcengine_v1_driver.get_dynamic_config_value') as mock_config, \
             patch('task.visual_drivers.seedance_volcengine_v1_driver.get_config', return_value={}):

            def side_effect(*keys, default=None):
                return {
                    ('volcengine', 'api_key'): 'test_key',
                    ('timeout', 'request_timeout'): 30,
                    ('server', 'is_local'): False,
                    ('test_mode', 'enabled'): False,
                    ('test_mode', 'mock_videos'): {},
                }.get(keys, default)

            mock_config.side_effect = side_effect
            driver = Seedance25VolcengineV1Driver()

        self.assertEqual(driver.driver_name, 'seedance_2_5_volcengine_v1')
        self.assertEqual(driver.driver_type, TaskTypeId.SEEDANCE_2_5_IMAGE_TO_VIDEO)
        self.assertEqual(driver._model, 'doubao-seedance-2-5-260628')


class TestSeedance25BuildRequest(unittest.TestCase):
    """Seedance 2.5 build_create_request"""

    def setUp(self):
        self.driver = _create_2_5_driver()

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_multi_reference_images_and_audio(self, mock_compress, mock_upload_cdn):
        """多参考图 + 参考音频：校验 model 名下发为 2.5，content 含 reference_image 与 reference_audio"""
        mock_compress.return_value = (True, 'https://cdn.example.com/ref.jpg', None)
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/audio.mp3', None)
        ai_tool = _make_ai_tool(
            prompt='果茶宣传',
            image_path=None,
            extra_config={'image_mode': 'multi_reference', 'generate_audio': True},
            reference_images=json.dumps(['http://example.com/ref1.jpg', 'http://example.com/ref2.jpg']),
            audio_path='http://example.com/audio.mp3',
        )

        result = self.driver.build_create_request(ai_tool)

        payload = result['json']
        # model 名为 2.5
        self.assertEqual(payload['model'], 'doubao-seedance-2-5-260628')
        self.assertTrue(payload['generate_audio'])
        # content 含 2 张 reference_image + 1 段 reference_audio
        content = payload['content']
        image_items = [c for c in content if c['type'] == 'image_url']
        audio_items = [c for c in content if c['type'] == 'audio_url']
        self.assertEqual(len(image_items), 2)
        for item in image_items:
            self.assertEqual(item.get('role'), 'reference_image')
        self.assertEqual(len(audio_items), 1)
        self.assertEqual(audio_items[0].get('role'), 'reference_audio')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_pure_audio_input(self, mock_compress, mock_upload_cdn):
        """纯音频输入（无图无视频）：content 仅含 text + reference_audio，无 image_url"""
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/audio.mp3', None)
        ai_tool = _make_ai_tool(
            prompt='用这段音频生成视频',
            image_path=None,
            extra_config={'image_mode': 'multi_reference'},
            audio_path='http://example.com/audio.mp3',
        )

        result = self.driver.build_create_request(ai_tool)

        content = result['json']['content']
        audio_items = [c for c in content if c['type'] == 'audio_url']
        image_items = [c for c in content if c['type'] == 'image_url']
        self.assertEqual(len(audio_items), 1)
        self.assertEqual(audio_items[0].get('role'), 'reference_audio')
        self.assertEqual(len(image_items), 0)

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.prepare_seedance_reference_video_sync',
           return_value=(True, 'http://example.com/video.mp4', None, []))
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_reference_video_uses_adaptive_ratio_and_follow_duration(
        self, mock_compress, mock_upload_cdn, mock_prepare
    ):
        """2.5 + 参考视频：显式 omni_reference_task_type=edit，ratio=adaptive、duration=-1"""
        mock_compress.return_value = (True, 'https://cdn.example.com/ref.jpg', None)
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/video.mp4', None)
        ai_tool = _make_ai_tool(
            prompt='参考视频1的内容进行视频复刻，带货商品为图片1',
            extra_config={'image_mode': 'multi_reference'},
            reference_images=json.dumps(['http://example.com/product.jpg']),
            video_path='http://example.com/ref.mp4',
            ratio='9:16',
            duration=5,
        )

        payload = self.driver.build_create_request(ai_tool)['json']
        self.assertEqual(payload['omni_reference_task_type'], 'edit')
        self.assertEqual(payload['ratio'], 'adaptive')
        self.assertEqual(payload['duration'], -1)

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.prepare_seedance_reference_video_sync',
           return_value=(True, 'http://example.com/video.mp4', None, []))
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.is_video_edit_billing_task')
    def test_reference_video_edit_uses_shared_predicate(
        self, mock_predicate, mock_upload_cdn, mock_prepare
    ):
        """驱动 edit 判定必须走共享谓词（与计价层同源），不得内联条件"""
        mock_predicate.return_value = True
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/video.mp4', None)
        ai_tool = _make_ai_tool(
            prompt='参考视频编辑',
            extra_config={'image_mode': 'multi_reference'},
            video_path='http://example.com/ref.mp4',
            ratio='9:16',
            duration=5,
        )

        payload = self.driver.build_create_request(ai_tool)['json']

        mock_predicate.assert_called_once_with(
            self.driver.driver_type, 'http://example.com/ref.mp4'
        )
        self.assertEqual(payload['omni_reference_task_type'], 'edit')

    def test_text_to_video_keeps_user_ratio_and_duration(self):
        """2.5 文生视频仍下发用户比例和时长，且不下发 omni_reference_task_type"""
        ai_tool = _make_ai_tool(
            prompt='一只猫在海滩上漫步',
            image_path=None,
            extra_config={'generate_audio': True},
            ratio='9:16',
            duration=5,
        )
        payload = self.driver.build_create_request(ai_tool)['json']
        self.assertEqual(payload['ratio'], '9:16')
        self.assertEqual(payload['duration'], 5)
        self.assertNotIn('omni_reference_task_type', payload)


class TestSeedance20ReferenceVideoKeepsUserParams(unittest.TestCase):
    """2.0 + 参考视频仍下发用户比例和时长，不被 2.5 编辑规则影响"""

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.prepare_seedance_reference_video_sync',
           return_value=(True, 'http://example.com/video.mp4', None, []))
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    def test_20_reference_video_keeps_user_ratio_and_duration(self, mock_upload_cdn, mock_prepare):
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/video.mp4', None)
        driver = _create_volcengine_driver(driver_type=23, model_name='doubao-seedance-2-0-260128')
        ai_tool = _make_ai_tool(
            prompt='参考视频1的内容进行视频复刻',
            extra_config={'image_mode': 'multi_reference'},
            video_path='http://example.com/ref.mp4',
            ratio='9:16',
            duration=5,
        )
        payload = driver.build_create_request(ai_tool)['json']
        self.assertEqual(payload['ratio'], '9:16')
        self.assertEqual(payload['duration'], 5)
        self.assertNotIn('omni_reference_task_type', payload)


class TestPureAudioRoutingVolcengine(unittest.TestCase):
    """纯音频路由兜底：无 image_mode 提示 / image_mode=first_last_frame 时，
    驱动自动改判 multi_reference（覆盖 CLI、storyboard 等非 server 入口）。
    用 2.0 标准版驱动隔离测试路由逻辑。"""

    def setUp(self):
        self.driver = _create_volcengine_driver(driver_type=23, model_name='doubao-seedance-2-0-260128')

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_pure_audio_no_image_mode_hint(self, mock_compress, mock_upload_cdn):
        """仅有音频、无图片、extra_config 未声明 image_mode → 路由到 multi_reference"""
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/audio.mp3', None)
        ai_tool = _make_ai_tool(
            prompt='参考音频生成',
            image_path=None,
            extra_config={},  # 无 image_mode 提示
            audio_path='http://example.com/audio.mp3',
        )

        result = self.driver.build_create_request(ai_tool)

        content = result['json']['content']
        audio_items = [c for c in content if c['type'] == 'audio_url']
        image_items = [c for c in content if c['type'] == 'image_url']
        # 不应被误判为「未找到可用图片」错误，也不应仅含 text
        self.assertEqual(len(audio_items), 1)
        self.assertEqual(audio_items[0].get('role'), 'reference_audio')
        self.assertEqual(len(image_items), 0)

    @patch('task.visual_drivers.seedance_volcengine_v1_driver.upload_media_to_cdn_sync')
    @patch('task.visual_drivers.seedance_volcengine_v1_driver.compress_and_upload_image_sync')
    def test_pure_audio_with_first_last_frame_mode(self, mock_compress, mock_upload_cdn):
        """仅有音频、image_mode=first_last_frame（非 server 入口）→ 仍路由到 multi_reference"""
        mock_upload_cdn.return_value = (True, 'https://cdn.example.com/audio.mp3', None)
        ai_tool = _make_ai_tool(
            prompt='参考音频生成',
            image_path=None,
            extra_config={'image_mode': 'first_last_frame'},
            audio_path='http://example.com/audio.mp3',
        )

        result = self.driver.build_create_request(ai_tool)

        content = result['json']['content']
        audio_items = [c for c in content if c['type'] == 'audio_url']
        self.assertEqual(len(audio_items), 1)
        self.assertEqual(audio_items[0].get('role'), 'reference_audio')


if __name__ == '__main__':
    unittest.main()
