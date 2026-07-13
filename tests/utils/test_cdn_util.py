"""
CDNUtil 单元测试

测试 CDN URL 判断、获取、签名、刷新等纯逻辑方法。
所有外部依赖（config、model、QiniuFileStorage）均使用 mock。
"""
import sys
import unittest
from unittest.mock import patch, MagicMock

# Mock 外部依赖（import 前置）
_saved_modules = {
    'config.config_util': sys.modules.get('config.config_util'),
    'utils.file_storage': sys.modules.get('utils.file_storage'),
    'utils.file_storage.qiniu_storage': sys.modules.get('utils.file_storage.qiniu_storage'),
    'utils.project_path': sys.modules.get('utils.project_path'),
    'model.media_file_mapping': sys.modules.get('model.media_file_mapping'),
    'model.database': sys.modules.get('model.database'),
}

sys.modules['config.config_util'] = MagicMock()
sys.modules['utils.file_storage'] = MagicMock()
sys.modules['utils.file_storage.qiniu_storage'] = MagicMock()
sys.modules['utils.project_path'] = MagicMock()
sys.modules['model.media_file_mapping'] = MagicMock()
sys.modules['model.database'] = MagicMock()

from utils.cdn_util import CDNUtil, CDNStatus


class TestIsCdnUrl(unittest.TestCase):
    """测试 CDNUtil.is_cdn_url()"""

    @patch('config.config_util.get_dynamic_config_value')
    def test_matching_long_term_domain(self, mock_get_config):
        """匹配 qiniu_long_term CDN 域名返回 True"""
        def side_effect(section, subsection, key, default=""):
            if subsection == 'qiniu_long_term' and key == 'cdn_domain':
                return 'cdn.example.com'
            return ''
        mock_get_config.side_effect = side_effect

        self.assertTrue(CDNUtil.is_cdn_url('https://cdn.example.com/upload/img/a.png'))

    @patch('config.config_util.get_dynamic_config_value')
    def test_matching_qiniu_domain(self, mock_get_config):
        """匹配 qiniu CDN 域名返回 True"""
        def side_effect(section, subsection, key, default=""):
            if subsection == 'qiniu' and key == 'cdn_domain':
                return 'qiniu.example.com'
            return ''
        mock_get_config.side_effect = side_effect

        self.assertTrue(CDNUtil.is_cdn_url('https://qiniu.example.com/upload/img/a.png'))

    @patch('config.config_util.get_dynamic_config_value')
    def test_external_url_returns_false(self, mock_get_config):
        """外部 URL 返回 False"""
        mock_get_config.return_value = 'cdn.example.com'

        self.assertFalse(CDNUtil.is_cdn_url('https://other-cdn.com/image.png'))

    @patch('config.config_util.get_dynamic_config_value')
    def test_empty_string_returns_false(self, mock_get_config):
        """空字符串返回 False"""
        mock_get_config.return_value = ''
        self.assertFalse(CDNUtil.is_cdn_url(''))

    @patch('config.config_util.get_dynamic_config_value')
    def test_none_returns_false(self, mock_get_config):
        """None 返回 False"""
        mock_get_config.return_value = ''
        self.assertFalse(CDNUtil.is_cdn_url(None))

    @patch('config.config_util.get_dynamic_config_value')
    def test_no_netloc_returns_false(self, mock_get_config):
        """没有域名的路径返回 False"""
        mock_get_config.return_value = 'cdn.example.com'
        self.assertFalse(CDNUtil.is_cdn_url('/upload/img/a.png'))

    @patch('config.config_util.get_dynamic_config_value')
    def test_exception_returns_false(self, mock_get_config):
        """配置获取异常返回 False"""
        mock_get_config.side_effect = Exception("config error")
        self.assertFalse(CDNUtil.is_cdn_url('https://cdn.example.com/img.png'))


class TestGetMediaUrl(unittest.TestCase):
    """测试 CDNUtil.get_media_url()"""

    def test_no_mapping_id_returns_not_enabled(self):
        """无 mapping_id 返回 (local_url, NOT_ENABLED)"""
        url, status = CDNUtil.get_media_url(None, 'http://localhost/img.png')
        self.assertEqual(url, 'http://localhost/img.png')
        self.assertEqual(status, CDNStatus.NOT_ENABLED)

    def test_no_mapping_id_no_local_returns_not_enabled(self):
        """无 mapping_id 且无 local_url 返回 (None, NOT_ENABLED)"""
        url, status = CDNUtil.get_media_url(None)
        self.assertIsNone(url)
        self.assertEqual(status, CDNStatus.NOT_ENABLED)

    @patch('utils.cdn_util.CDNUtil.get_cdn_url')
    def test_cdn_ready_returns_cdn_url(self, mock_get_cdn):
        """CDN 已就绪返回 (cdn_url, READY)"""
        mock_get_cdn.return_value = 'https://cdn.example.com/signed/img.png'

        url, status = CDNUtil.get_media_url(123, 'http://localhost/img.png')
        self.assertEqual(url, 'https://cdn.example.com/signed/img.png')
        self.assertEqual(status, CDNStatus.READY)

    @patch('utils.cdn_util.CDNUtil.get_cdn_url')
    def test_cdn_pending_returns_none(self, mock_get_cdn):
        """CDN 处理中返回 (None, PENDING)"""
        mock_get_cdn.return_value = None

        url, status = CDNUtil.get_media_url(123, 'http://localhost/img.png')
        self.assertIsNone(url)
        self.assertEqual(status, CDNStatus.PENDING)

    @patch('utils.cdn_util.CDNUtil.get_cdn_url')
    def test_cdn_error_returns_local_url(self, mock_get_cdn):
        """CDN 异常时 fallback 到 (local_url, ERROR)"""
        mock_get_cdn.side_effect = Exception("db error")

        url, status = CDNUtil.get_media_url(123, 'http://localhost/img.png')
        self.assertEqual(url, 'http://localhost/img.png')
        self.assertEqual(status, CDNStatus.ERROR)


class TestGetSignedDownloadUrl(unittest.TestCase):
    """测试 CDNUtil.get_signed_download_url()"""

    @patch('utils.file_storage.try_get_file_storage')
    @patch('config.config_util.get_dynamic_config_value')
    def test_matching_long_term_domain(self, mock_get_config, mock_try_get_storage):
        """匹配 qiniu_long_term 域名时生成签名 URL"""
        def side_effect(section, subsection, key, default=""):
            mapping = {
                ('file_storage', 'qiniu_long_term', 'cdn_domain'): 'cdn.example.com',
                ('file_storage', 'qiniu', 'cdn_domain'): '',
            }
            return mapping.get((section, subsection, key), default)
        mock_get_config.side_effect = side_effect

        # mock 工厂入口（参数化单例），避免触发真实 _load_config / QiniuFileStorage 实例化
        mock_storage = MagicMock()
        mock_storage.get_download_url.return_value = 'https://cdn.example.com/img.png?signed=1'
        mock_try_get_storage.return_value = mock_storage

        result = CDNUtil.get_signed_download_url(
            'https://cdn.example.com/upload/img/a.png', 'my_file.png'
        )

        self.assertEqual(result, 'https://cdn.example.com/img.png?signed=1')
        mock_try_get_storage.assert_called_once_with(section='qiniu_long_term')
        mock_storage.get_download_url.assert_called_once_with(
            'upload/img/a.png', expires=100800, attname='my_file.png'
        )

    @patch('config.config_util.get_dynamic_config_value')
    def test_unmatched_domain_returns_none(self, mock_get_config):
        """未匹配的域名返回 None"""
        mock_get_config.return_value = ''

        result = CDNUtil.get_signed_download_url(
            'https://unknown-cdn.com/img.png', 'file.png'
        )
        self.assertIsNone(result)

    @patch('utils.file_storage.try_get_file_storage', return_value=None)
    @patch('config.config_util.get_dynamic_config_value')
    def test_incomplete_config_returns_none(self, mock_get_config, mock_try_get_storage):
        """配置不完整（factory 返回 None）时返回 None

        配置完整性的校验已下沉到 try_get_file_storage 内部（缺失返回 None），
        这里 mock factory 返回 None 模拟该场景，验证 cdn_util 的 None 分支。
        """
        def side_effect(section, subsection, key, default=""):
            if key == 'cdn_domain':
                return 'cdn.example.com'
            return ''  # access_key, secret_key, bucket_name 都为空
        mock_get_config.side_effect = side_effect

        result = CDNUtil.get_signed_download_url(
            'https://cdn.example.com/img.png', 'file.png'
        )
        self.assertIsNone(result)

    @patch('config.config_util.get_dynamic_config_value')
    def test_exception_returns_none(self, mock_get_config):
        """异常时返回 None"""
        mock_get_config.side_effect = Exception("config error")
        result = CDNUtil.get_signed_download_url('https://cdn.example.com/img.png', 'file.png')
        self.assertIsNone(result)


class TestRefreshCdnSignedUrl(unittest.TestCase):
    """测试 CDNUtil.refresh_cdn_signed_url()"""

    def test_empty_url_returns_empty(self):
        """空字符串原样返回"""
        self.assertEqual(CDNUtil.refresh_cdn_signed_url(''), '')

    def test_none_url_returns_none(self):
        """None 原样返回"""
        self.assertIsNone(CDNUtil.refresh_cdn_signed_url(None))

    @patch('utils.cdn_util.CDNUtil.is_cdn_url', return_value=False)
    def test_non_cdn_url_returns_original(self, mock_is_cdn):
        """非 CDN URL 原样返回"""
        url = 'http://localhost:8000/upload/img.png'
        self.assertEqual(CDNUtil.refresh_cdn_signed_url(url), url)

    @patch('utils.file_storage.try_get_file_storage')
    @patch('config.config_util.get_dynamic_config_value')
    @patch('utils.cdn_util.CDNUtil.is_cdn_url', return_value=True)
    def test_cdn_url_refreshed(self, mock_is_cdn, mock_get_config, mock_try_get_storage):
        """CDN URL 成功刷新签名"""
        def side_effect(section, subsection, key, default=""):
            mapping = {
                ('file_storage', 'qiniu_long_term', 'cdn_domain'): 'cdn.example.com',
                ('file_storage', 'qiniu', 'cdn_domain'): '',
            }
            return mapping.get((section, subsection, key), default)
        mock_get_config.side_effect = side_effect

        # mock 工厂入口，避免触发真实 _load_config / QiniuFileStorage 实例化
        mock_storage = MagicMock()
        mock_storage.get_download_url.return_value = 'https://cdn.example.com/img.png?fresh_sig=1'
        mock_try_get_storage.return_value = mock_storage

        result = CDNUtil.refresh_cdn_signed_url('https://cdn.example.com/upload/img.png?old_sig=x')
        self.assertEqual(result, 'https://cdn.example.com/img.png?fresh_sig=1')

    @patch('utils.cdn_util.CDNUtil.is_cdn_url', return_value=True)
    @patch('config.config_util.get_dynamic_config_value')
    def test_exception_returns_original_url(self, mock_get_config, mock_is_cdn):
        """刷新异常时返回原始 URL"""
        mock_get_config.side_effect = Exception("unexpected")
        url = 'https://cdn.example.com/img.png?old_sig=x'
        self.assertEqual(CDNUtil.refresh_cdn_signed_url(url), url)


class TestCdnStatusConstants(unittest.TestCase):
    """测试 CDNStatus 常量值"""

    def test_status_values(self):
        """CDNStatus 常量值正确"""
        self.assertEqual(CDNStatus.READY, "ready")
        self.assertEqual(CDNStatus.PENDING, "pending")
        self.assertEqual(CDNStatus.NOT_ENABLED, "not_enabled")
        self.assertEqual(CDNStatus.ERROR, "error")


# 恢复 sys.modules
for _key, _orig in _saved_modules.items():
    if _orig is not None:
        sys.modules[_key] = _orig
    else:
        sys.modules.pop(_key, None)


if __name__ == '__main__':
    unittest.main()
