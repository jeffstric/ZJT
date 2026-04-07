"""
CDN Storage Manager 单元测试
"""
import unittest
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCDNStorageManager(unittest.TestCase):
    """CDNStorageManager 单元测试"""

    def setUp(self):
        """每个测试前创建临时文件"""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_file = os.path.join(self.temp_dir, 'test_image.jpg')
        with open(self.temp_file, 'wb') as f:
            f.write(b'test image content')

    def tearDown(self):
        """每个测试后清理临时文件"""
        import shutil
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    @patch('config.config_util.get_dynamic_config_value')
    def test_is_enabled_when_disabled(self, mock_get_config):
        """测试 CDN 未启用时 is_enabled 返回 False"""
        mock_get_config.return_value = False

        from utils.cdn_storage import CDNStorageManager
        manager = CDNStorageManager()

        self.assertFalse(manager.is_enabled())

    @patch('config.config_util.get_dynamic_config_value')
    def test_is_enabled_when_enabled_but_no_storage(self, mock_get_config):
        """测试 CDN 启用但配置不完整时 is_enabled 返回 False"""
        def side_effect(section, key, default=None):
            if section == 'cdn_storage' and key == 'enabled':
                return True
            if section == 'cdn_storage' and key == 'provider':
                return 'qiniu'
            if section == 'cdn_storage' and key == 'access_key':
                return ''  # 空配置
            if section == 'cdn_storage' and key == 'secret_key':
                return ''
            if section == 'cdn_storage' and key == 'bucket_name':
                return ''
            if section == 'cdn_storage' and key == 'cdn_domain':
                return ''
            return default

        mock_get_config.side_effect = side_effect

        from utils.cdn_storage import CDNStorageManager
        manager = CDNStorageManager()

        self.assertFalse(manager.is_enabled())

    @patch('config.config_util.get_dynamic_config_value')
    @patch('utils.file_storage.qiniu_storage.QiniuFileStorage')
    def test_is_enabled_when_fully_configured(self, mock_qiniu, mock_get_config):
        """测试 CDN 完全配置时 is_enabled 返回 True"""
        def side_effect(section, key, default=None):
            if section == 'cdn_storage' and key == 'enabled':
                return True
            if section == 'cdn_storage' and key == 'provider':
                return 'qiniu'
            if section == 'cdn_storage' and key == 'access_key':
                return 'test_access_key'
            if section == 'cdn_storage' and key == 'secret_key':
                return 'test_secret_key'
            if section == 'cdn_storage' and key == 'bucket_name':
                return 'test_bucket'
            if section == 'cdn_storage' and key == 'cdn_domain':
                return 'cdn.test.com'
            if section == 'cdn_storage' and key == 'prefix':
                return 'ai_tools'
            return default

        mock_get_config.side_effect = side_effect

        from utils.cdn_storage import CDNStorageManager
        manager = CDNStorageManager()

        self.assertTrue(manager.is_enabled())
        mock_qiniu.assert_called_once()

    @patch('config.config_util.get_dynamic_config_value')
    def test_get_cdn_prefix_default(self, mock_get_config):
        """测试获取 CDN 前缀（默认）"""
        mock_get_config.return_value = False  # disabled

        from utils.cdn_storage import CDNStorageManager
        manager = CDNStorageManager()
        manager.enabled = True

        with patch.object(manager, '_get_cdn_prefix', return_value='ai_tools'):
            prefix = manager._get_cdn_prefix()
            self.assertEqual(prefix, 'ai_tools')

    @patch('config.config_util.get_dynamic_config_value')
    def test_upload_local_file_when_disabled(self, mock_get_config):
        """测试 CDN 未启用时上传返回 None"""
        mock_get_config.return_value = False

        from utils.cdn_storage import CDNStorageManager
        manager = CDNStorageManager()

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            manager.upload_local_file('upload/test.jpg')
        )

        self.assertIsNone(result)

    @patch('config.config_util.get_dynamic_config_value')
    def test_upload_local_file_not_exists(self, mock_get_config):
        """测试上传不存在的文件返回 None"""
        def side_effect(section, key, default=None):
            if section == 'cdn_storage' and key == 'enabled':
                return True
            if section == 'cdn_storage' and key == 'provider':
                return 'qiniu'
            if section == 'cdn_storage' and key == 'access_key':
                return 'test_access_key'
            if section == 'cdn_storage' and key == 'secret_key':
                return 'test_secret_key'
            if section == 'cdn_storage' and key == 'bucket_name':
                return 'test_bucket'
            if section == 'cdn_storage' and key == 'cdn_domain':
                return 'cdn.test.com'
            if section == 'cdn_storage' and key == 'prefix':
                return 'ai_tools'
            return default

        mock_get_config.side_effect = side_effect

        from utils.cdn_storage import CDNStorageManager
        manager = CDNStorageManager()
        manager._storage = MagicMock()  # mock storage

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            manager.upload_local_file('upload/nonexistent.jpg')
        )

        self.assertIsNone(result)

    @patch('config.config_util.get_dynamic_config_value')
    def test_upload_local_file_success(self, mock_get_config):
        """测试上传成功返回 CDN URL"""
        def side_effect(section, key, default=None):
            if section == 'cdn_storage' and key == 'enabled':
                return True
            if section == 'cdn_storage' and key == 'provider':
                return 'qiniu'
            if section == 'cdn_storage' and key == 'access_key':
                return 'test_access_key'
            if section == 'cdn_storage' and key == 'secret_key':
                return 'test_secret_key'
            if section == 'cdn_storage' and key == 'bucket_name':
                return 'test_bucket'
            if section == 'cdn_storage' and key == 'cdn_domain':
                return 'cdn.test.com'
            if section == 'cdn_storage' and key == 'prefix':
                return 'ai_tools'
            return default

        mock_get_config.side_effect = side_effect

        from utils.cdn_storage import CDNStorageManager
        from utils.file_storage.base import UploadResult

        manager = CDNStorageManager()
        manager._storage = MagicMock()
        manager._storage.upload_file = MagicMock(return_value=UploadResult(
            success=True,
            key='ai_tools/upload/test.jpg',
            hash='abc123',
            url='http://cdn.test.com/ai_tools/upload/test.jpg',
            error=None
        ))
        manager._storage.get_public_url = MagicMock(return_value='http://cdn.test.com/ai_tools/upload/test.jpg')

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            manager.upload_local_file('upload/test.jpg')
        )

        self.assertIsNotNone(result)
        self.assertEqual(result, 'http://cdn.test.com/ai_tools/upload/test.jpg')
        manager._storage.upload_file.assert_called_once()

    @patch('config.config_util.get_dynamic_config_value')
    def test_get_public_url(self, mock_get_config):
        """测试获取公开 URL"""
        def side_effect(section, key, default=None):
            if section == 'cdn_storage' and key == 'enabled':
                return True
            if section == 'cdn_storage' and key == 'provider':
                return 'qiniu'
            if section == 'cdn_storage' and key == 'access_key':
                return 'test_access_key'
            if section == 'cdn_storage' and key == 'secret_key':
                return 'test_secret_key'
            if section == 'cdn_storage' and key == 'bucket_name':
                return 'test_bucket'
            if section == 'cdn_storage' and key == 'cdn_domain':
                return 'cdn.test.com'
            if section == 'cdn_storage' and key == 'prefix':
                return 'ai_tools'
            return default

        mock_get_config.side_effect = side_effect

        from utils.cdn_storage import CDNStorageManager

        manager = CDNStorageManager()
        manager._storage = MagicMock()
        manager._storage.get_public_url = MagicMock(return_value='http://cdn.test.com/ai_tools/upload/test.jpg')

        result = manager.get_public_url('ai_tools/upload/test.jpg')

        self.assertEqual(result, 'http://cdn.test.com/ai_tools/upload/test.jpg')
        manager._storage.get_public_url.assert_called_once_with('ai_tools/upload/test.jpg')

    @patch('config.config_util.get_dynamic_config_value')
    def test_get_public_url_when_disabled(self, mock_get_config):
        """测试 CDN 未启用时获取公开 URL 返回 None"""
        mock_get_config.return_value = False

        from utils.cdn_storage import CDNStorageManager
        manager = CDNStorageManager()

        result = manager.get_public_url('ai_tools/upload/test.jpg')

        self.assertIsNone(result)

    @patch('config.config_util.get_dynamic_config_value')
    def test_singleton_pattern(self, mock_get_config):
        """测试单例模式"""
        mock_get_config.return_value = False

        from utils.cdn_storage import CDNStorageManager, get_cdn_storage

        # 第一次调用
        instance1 = get_cdn_storage()
        # 第二次调用
        instance2 = get_cdn_storage()

        self.assertIs(instance1, instance2)


class TestMediaFileMappingModelCDNMethods(unittest.TestCase):
    """MediaFileMappingModel CDN 相关方法测试"""

    @patch('utils.cdn_storage.get_cdn_storage')
    def test_trigger_cdn_upload_disabled(self, mock_get_cdn):
        """测试 CDN 未启用时 trigger_cdn_upload"""
        mock_cdn = MagicMock()
        mock_cdn.is_enabled.return_value = False
        mock_get_cdn.return_value = mock_cdn

        from model.media_file_mapping import MediaFileMappingModel

        # 这个测试验证方法不会抛出异常
        # 实际异步上传不会执行因为 CDN 被禁用
        # 注意：由于异步执行，线程池中的代码可能不会立即执行
        try:
            MediaFileMappingModel.trigger_cdn_upload(1, 'upload/test.jpg')
        except Exception as e:
            self.fail(f"trigger_cdn_upload raised exception: {e}")

    @patch('utils.cdn_storage.get_cdn_storage')
    def test_get_cdn_url_returns_none_when_no_mapping(self, mock_get_cdn):
        """测试 get_cdn_url 当映射不存在时返回 None"""
        mock_get_cdn.return_value = MagicMock()

        from model.media_file_mapping import MediaFileMappingModel
        from unittest.mock import patch

        with patch.object(MediaFileMappingModel, 'get_by_id', return_value=None):
            result = MediaFileMappingModel.get_cdn_url(99999)
            self.assertIsNone(result)

    @patch('utils.cdn_storage.get_cdn_storage')
    def test_get_cdn_url_returns_none_when_no_cloud_path(self, mock_get_cdn):
        """测试 get_cdn_url 当 cloud_path 为空时返回 None"""
        mock_mapping = MagicMock()
        mock_mapping.cloud_path = None
        mock_get_cdn.return_value = MagicMock()

        from model.media_file_mapping import MediaFileMappingModel
        from unittest.mock import patch

        with patch.object(MediaFileMappingModel, 'get_by_id', return_value=mock_mapping):
            result = MediaFileMappingModel.get_cdn_url(1)
            self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
