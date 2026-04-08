"""
CDN Storage 单元测试（针对 MediaFileMappingModel 的 CDN 功能）
"""
import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))


class TestMediaFileMappingModelCDNMethods(unittest.TestCase):
    """MediaFileMappingModel CDN 相关方法测试"""

    @patch('config.config_util.get_dynamic_config_value')
    def test_trigger_cdn_upload_disabled(self, mock_get_config):
        """测试 CDN 未启用时 trigger_cdn_upload 不会抛出异常"""
        mock_get_config.return_value = False

        from model.media_file_mapping import MediaFileMappingModel

        try:
            MediaFileMappingModel.trigger_cdn_upload(1, 'upload/test.jpg')
        except Exception as e:
            self.fail(f"trigger_cdn_upload raised exception: {e}")

    @patch('model.media_file_mapping.MediaFileMappingModel._get_cdn_storage')
    def test_get_cdn_url_returns_none_when_no_mapping(self, mock_get_cdn_storage):
        """测试 get_cdn_url 当映射不存在时返回 None"""
        mock_get_cdn_storage.return_value = (MagicMock(), True)

        from model.media_file_mapping import MediaFileMappingModel

        with patch.object(MediaFileMappingModel, 'get_by_id', return_value=None):
            result = MediaFileMappingModel.get_cdn_url(99999)
            self.assertIsNone(result)

    @patch('model.media_file_mapping.MediaFileMappingModel._get_cdn_storage')
    def test_get_cdn_url_returns_none_when_no_cloud_path(self, mock_get_cdn_storage):
        """测试 get_cdn_url 当 cloud_path 为空时返回 None"""
        mock_mapping = MagicMock()
        mock_mapping.cloud_path = None
        mock_get_cdn_storage.return_value = (MagicMock(), True)

        from model.media_file_mapping import MediaFileMappingModel

        with patch.object(MediaFileMappingModel, 'get_by_id', return_value=mock_mapping):
            result = MediaFileMappingModel.get_cdn_url(1)
            self.assertIsNone(result)

    @patch('config.config_util.get_dynamic_config_value')
    def test_get_cdn_storage_raises_when_enabled_but_not_configured(self, mock_get_config):
        """测试 auto_upload=true 但配置不完整时抛出异常"""
        def side_effect(section, key, default=None):
            if section == 'server' and key == 'auto_upload_to_cdn':
                return True
            if section == 'file_storage' and key == 'qiniu_long_term':
                return {'access_key': '', 'secret_key': '', 'bucket_name': '', 'cdn_domain': ''}
            return default

        mock_get_config.side_effect = side_effect

        from model.media_file_mapping import MediaFileMappingModel

        with self.assertRaises(ValueError) as context:
            MediaFileMappingModel._get_cdn_storage()

        self.assertIn('配置不完整', str(context.exception))


if __name__ == '__main__':
    unittest.main()
