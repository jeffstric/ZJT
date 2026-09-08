"""
register_uploaded_file_mapping 单元测试

覆盖上传链路接入 CDN 的注册函数：
- 开关门（auto_upload_to_cdn 关闭时跳过）
- 正常注册（create + trigger_cdn_upload）
- 同路径查重复用
- 空路径 / 注册异常不阻断上传主流程
- MediaFileEntity.TTS 枚举
"""
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestRegisterUploadedFileMapping(unittest.TestCase):
    """上传文件注册 CDN mapping 的单元测试"""

    @patch('config.config_util.get_config')
    def test_returns_none_when_cdn_disabled(self, mock_get_config):
        """CDN 开关关闭时应直接跳过，不建 mapping 不触发上传"""
        mock_get_config.return_value = {"server": {"auto_upload_to_cdn": False}}

        from utils.media_mapping_util import register_uploaded_file_mapping

        with patch('model.media_file_mapping.MediaFileMappingModel.create') as mock_create, \
             patch('utils.cdn_util.CDNUtil.trigger_cdn_upload') as mock_trigger:
            result = register_uploaded_file_mapping(
                1, 'upload/workflow/1/a.png', 5, 'never_expire'
            )

        self.assertIsNone(result)
        mock_create.assert_not_called()
        mock_trigger.assert_not_called()

    @patch('config.config_util.get_config')
    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.media_file_mapping.MediaFileMappingModel.get_by_local_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_creates_mapping_and_triggers_upload(
        self, mock_create, mock_get_by_local_path, mock_trigger, mock_get_config
    ):
        """正常路径：无重复记录时应 create 并 trigger 上传，返回 mapping_id"""
        mock_get_config.return_value = {"server": {"auto_upload_to_cdn": True}}
        mock_get_by_local_path.return_value = None
        mock_create.return_value = 100

        from utils.media_mapping_util import register_uploaded_file_mapping

        result = register_uploaded_file_mapping(
            12, 'upload/workflow/12/media_20260906_100000_ab12cd34.mp4', 5, 'never_expire'
        )

        self.assertEqual(result, 100)
        mock_create.assert_called_once()
        create_kwargs = mock_create.call_args[1]
        self.assertEqual(create_kwargs['local_path'], 'upload/workflow/12/media_20260906_100000_ab12cd34.mp4')
        self.assertEqual(create_kwargs['entity_type'], 5)
        self.assertEqual(create_kwargs['policy_code'], 'never_expire')
        self.assertEqual(create_kwargs['media_type'], 'video/mp4')
        self.assertIsNone(create_kwargs['cloud_path'])
        mock_trigger.assert_called_once_with(100, 'upload/workflow/12/media_20260906_100000_ab12cd34.mp4')

    @patch('config.config_util.get_config')
    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.media_file_mapping.MediaFileMappingModel.get_by_local_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_reuses_existing_mapping_for_same_path(
        self, mock_create, mock_get_by_local_path, mock_trigger, mock_get_config
    ):
        """同路径已有 mapping 时应复用，不重复 create/trigger"""
        mock_get_config.return_value = {"server": {"auto_upload_to_cdn": True}}
        mock_existing = MagicMock()
        mock_existing.id = 88
        mock_get_by_local_path.return_value = mock_existing

        from utils.media_mapping_util import register_uploaded_file_mapping

        result = register_uploaded_file_mapping(
            1, 'upload/tts/result_audio/a.mp3', 7, 'never_expire'
        )

        self.assertEqual(result, 88)
        mock_create.assert_not_called()
        mock_trigger.assert_not_called()

    @patch('config.config_util.get_config')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_skips_empty_local_path(self, mock_create, mock_get_config):
        """空路径应直接跳过"""
        mock_get_config.return_value = {"server": {"auto_upload_to_cdn": True}}

        from utils.media_mapping_util import register_uploaded_file_mapping

        result = register_uploaded_file_mapping(1, '', 5, 'never_expire')

        self.assertIsNone(result)
        mock_create.assert_not_called()

    @patch('config.config_util.get_config')
    @patch('model.media_file_mapping.MediaFileMappingModel.get_by_local_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_swallows_create_exception(self, mock_create, mock_get_by_local_path, mock_get_config):
        """create 抛异常时不应向上传播（不阻断上传主流程），返回 None"""
        mock_get_config.return_value = {"server": {"auto_upload_to_cdn": True}}
        mock_get_by_local_path.return_value = None
        mock_create.side_effect = RuntimeError("db down")

        from utils.media_mapping_util import register_uploaded_file_mapping

        result = register_uploaded_file_mapping(
            1, 'upload/workflow/1/a.png', 5, 'never_expire'
        )

        self.assertIsNone(result)

    @patch('config.config_util.get_config')
    @patch('utils.cdn_util.CDNUtil.trigger_cdn_upload')
    @patch('model.media_file_mapping.MediaFileMappingModel.get_by_local_path')
    @patch('model.media_file_mapping.MediaFileMappingModel.create')
    def test_swallows_trigger_exception(
        self, mock_create, mock_get_by_local_path, mock_trigger, mock_get_config
    ):
        """trigger 抛异常时同样不向上传播，返回 None（mapping 已建，可由补传任务重试）"""
        mock_get_config.return_value = {"server": {"auto_upload_to_cdn": True}}
        mock_get_by_local_path.return_value = None
        mock_create.return_value = 200
        mock_trigger.side_effect = RuntimeError("thread pool gone")

        from utils.media_mapping_util import register_uploaded_file_mapping

        result = register_uploaded_file_mapping(
            1, 'upload/workflow/1/a.png', 5, 'never_expire'
        )

        self.assertIsNone(result)

    def test_media_file_entity_tts_enum(self):
        """MediaFileEntity.TTS 枚举值与双向转换"""
        from model.media_file_mapping import MediaFileEntity

        self.assertEqual(MediaFileEntity.TTS, 7)
        self.assertEqual(MediaFileEntity.get_entity_name(7), 'tts')
        self.assertEqual(MediaFileEntity.from_entity_name('tts'), 7)
        self.assertEqual(MediaFileEntity.get_entity_name(5), 'workflow')
        self.assertEqual(MediaFileEntity.from_entity_name('workflow'), 5)

    def test_extract_local_path_from_tts_upload_url(self):
        """TTS upload_url 场景：从配置拼出的绝对 URL 提取相对路径"""
        from utils.media_mapping_util import extract_local_path_from_url

        url = "http://ailive.perseids.cn:11442/upload/tts/result_audio/tts_20260906_120000_ab12cd34.mp3"
        self.assertEqual(
            extract_local_path_from_url(url),
            "upload/tts/result_audio/tts_20260906_120000_ab12cd34.mp3"
        )
        # 相对路径形式同样支持
        self.assertEqual(
            extract_local_path_from_url("/upload/workflow/9/a.png"),
            "upload/workflow/9/a.png"
        )
        # 外部 URL 拒绝
        self.assertIsNone(extract_local_path_from_url("https://third-party.com/x.png"))


if __name__ == '__main__':
    unittest.main()
