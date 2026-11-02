"""
QiniuFileStorage.get_download_url 单元测试

重点验证 attname 包含非 ASCII 字符（中文）时是否正确 URL 编码，
避免签名时用原始中文、CDN 收到 percent-encoded 中文导致 401。
"""
import unittest
from unittest.mock import patch, MagicMock


class TestGetDownloadUrlAttnameEncoding(unittest.TestCase):
    """测试 get_download_url 的 attname URL 编码"""

    def _make_storage(self):
        """构造一个 QiniuFileStorage 实例（mock 掉 qiniu.Auth）"""
        with patch('utils.file_storage.qiniu_storage.qiniu.Auth'):
            from utils.file_storage.qiniu_storage import QiniuFileStorage
            storage = QiniuFileStorage(
                access_key="fake_ak",
                secret_key="fake_sk",
                bucket_name="fake_bucket",
                cdn_domain="cdn.example.com",
            )
            storage._auth = MagicMock()
            storage._auth.private_download_url.side_effect = lambda url, expires: url
            return storage

    def test_ascii_attname_not_encoded(self):
        """纯 ASCII attname 保持原样"""
        storage = self._make_storage()
        url = storage.get_download_url("test/file.mp4", attname="video.mp4")
        self.assertIn("attname=video.mp4", url)
        self.assertNotIn("%", url)

    def test_chinese_attname_is_encoded(self):
        """中文 attname 必须被 URL 编码，否则 CDN 签名不匹配 → 401"""
        storage = self._make_storage()
        url = storage.get_download_url("test/file.mp4", attname="第3集故事板_完整.mp4")
        # attname 应被 percent-encode
        self.assertIn("attname=%E7%AC%AC3%E9%9B%86", url)
        # 不应包含原始中文字符
        self.assertNotIn("第", url)
        self.assertNotIn("集", url)

    def test_no_attname_no_query(self):
        """无 attname 时 URL 不带 ?attname= 参数"""
        storage = self._make_storage()
        url = storage.get_download_url("test/file.mp4")
        self.assertNotIn("attname", url)

    def test_attname_with_spaces_encoded(self):
        """attname 含空格时被编码为 %20"""
        storage = self._make_storage()
        url = storage.get_download_url("test/file.mp4", attname="my video.mp4")
        self.assertIn("attname=my%20video.mp4", url)


class TestGetPublicUrlScheme(unittest.TestCase):
    """测试 get_public_url 协议跟随 server.https.enabled 配置

    背景：站点切换 HTTPS 后，硬编码 http:// 的下载链接会被浏览器按
    混合内容下载拦截（用户点击导出后看不到文件）。
    """

    def _make_storage(self):
        """构造一个 QiniuFileStorage 实例（mock 掉 qiniu.Auth）"""
        with patch('utils.file_storage.qiniu_storage.qiniu.Auth'):
            from utils.file_storage.qiniu_storage import QiniuFileStorage
            storage = QiniuFileStorage(
                access_key="fake_ak",
                secret_key="fake_sk",
                bucket_name="fake_bucket",
                cdn_domain="cdn.example.com",
            )
            storage._auth = MagicMock()
            storage._auth.private_download_url.side_effect = lambda url, expires: url
            return storage

    def test_https_enabled_uses_https(self):
        """server.https.enabled=true 时生成 https:// 链接"""
        storage = self._make_storage()
        with patch('utils.file_storage.qiniu_storage.get_config_value',
                   return_value=True) as mock_cfg:
            url = storage.get_public_url("2026-09-11/export.zip")
        mock_cfg.assert_called_once_with("server", "https", "enabled", default=False)
        self.assertTrue(url.startswith("https://cdn.example.com/"))
        self.assertNotIn("http://", url)

    def test_https_disabled_uses_http(self):
        """server.https.enabled=false 时保持 http:// 链接"""
        storage = self._make_storage()
        with patch('utils.file_storage.qiniu_storage.get_config_value',
                   side_effect=lambda *a, **k: k.get('default', None)):
            url = storage.get_public_url("2026-09-11/export.zip")
        self.assertTrue(url.startswith("http://cdn.example.com/"))

    def test_https_missing_falls_back_to_http(self):
        """配置缺失（get_config_value 返回 default=False）时保持 http://"""
        storage = self._make_storage()
        with patch('utils.file_storage.qiniu_storage.get_config_value',
                   side_effect=lambda *a, **k: k.get('default', None)):
            url = storage.get_public_url("a/b.png")
        self.assertTrue(url.startswith("http://"))

    def test_download_url_follows_https(self):
        """get_download_url（导出下载链路）同样跟随 https 配置"""
        storage = self._make_storage()
        with patch('utils.file_storage.qiniu_storage.get_config_value',
                   return_value=True):
            url = storage.get_download_url("world/export.zip", attname="世界.zip", expires=7200)
        self.assertTrue(url.startswith("https://cdn.example.com/world/export.zip?"))
        self.assertIn("attname=%E4%B8%96%E7%95%8C.zip", url)



class TestGetBrowserUploadInfo(unittest.TestCase):
    """测试 get_browser_upload_info 直传信息颁发（七牛 form 直传协议封装）"""

    def _make_storage(self, upload_host=""):
        with patch('utils.file_storage.qiniu_storage.qiniu.Auth'):
            from utils.file_storage.qiniu_storage import QiniuFileStorage
            storage = QiniuFileStorage(
                access_key="fake_ak",
                secret_key="fake_sk",
                bucket_name="fake_bucket",
                cdn_domain="cdn.example.com",
                upload_host=upload_host,
            )
            storage._auth = MagicMock()
            return storage

    def test_returns_token_bound_to_key_with_fsize_limit(self):
        """token 经 get_upload_token 颁发，policy 带 fsizeLimit 与 returnBody"""
        storage = self._make_storage(upload_host="https://up.example.com")
        with patch.object(storage, 'get_upload_token', return_value='tok') as mock_token:
            import asyncio
            info = asyncio.run(storage.get_browser_upload_info("upload/workflow/1/a.mp4", 200 * 1024 * 1024))
        self.assertEqual(info["direct_upload"], True)
        self.assertEqual(info["upload_url"], "https://up.example.com")
        self.assertEqual(info["key"], "upload/workflow/1/a.mp4")
        self.assertEqual(info["token"], "tok")
        policy = mock_token.call_args[1]['policy']
        self.assertEqual(policy['fsizeLimit'], 200 * 1024 * 1024)
        self.assertIn('$(key)', policy['returnBody'])

    def test_base_class_default_returns_none(self):
        """基类默认不支持浏览器直传（如 RunningHub 后端），端点据此降级"""
        import asyncio
        from utils.file_storage.base import BaseFileStorage

        class _Minimal(BaseFileStorage):
            async def upload_data(self, key, data, content_type=None):
                raise NotImplementedError

            async def upload_file(self, key, file_path, content_type=None):
                raise NotImplementedError

            def get_download_url(self, key, expires=3600):
                return key

            def get_public_url(self, key):
                return key

            async def delete(self, key):
                return True

        self.assertIsNone(asyncio.run(_Minimal().get_browser_upload_info("k", 100)))


class TestResolveBrowserUploadHost(unittest.TestCase):
    """测试直传域名解析：配置覆盖 → UC 查询（缓存）→ 默认华东域名"""

    def _make_storage(self, upload_host=""):
        with patch('utils.file_storage.qiniu_storage.qiniu.Auth'):
            from utils.file_storage.qiniu_storage import QiniuFileStorage
            return QiniuFileStorage(
                access_key="fake_ak",
                secret_key="fake_sk",
                bucket_name="fake_bucket",
                cdn_domain="cdn.example.com",
                upload_host=upload_host,
            )

    def tearDown(self):
        import utils.file_storage.qiniu_storage as qiniu_mod
        qiniu_mod._browser_upload_host_cache.pop(("fake_ak", "fake_bucket"), None)

    def test_override_preferred_without_uc_query(self):
        """构造传入 upload_host 覆盖时直接使用，不发 UC 查询"""
        import asyncio
        storage = self._make_storage(upload_host="up.example.com")
        host = asyncio.run(storage._resolve_browser_upload_host())
        self.assertEqual(host, "https://up.example.com")

    def test_uc_query_success_parses_and_caches(self):
        """UC 查询成功解析 acc.main 首个域名并写入进程缓存"""
        import asyncio
        from unittest.mock import AsyncMock

        storage = self._make_storage()

        class _FakeResp:
            def json(self):
                return {"up": {"acc": {"main": ["upload-cn-east-2.qiniup.com"]}}}

        class _FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *exc):
                return False

            async def get(self, url, params=None):
                return _FakeResp()

        with patch('utils.file_storage.qiniu_storage.httpx.AsyncClient', _FakeClient):
            host = asyncio.run(storage._resolve_browser_upload_host())
        self.assertEqual(host, "https://upload-cn-east-2.qiniup.com")
        # 第二次命中缓存：换一个会抛异常的 client 仍返回缓存值
        with patch('utils.file_storage.qiniu_storage.httpx.AsyncClient', side_effect=RuntimeError):
            host2 = asyncio.run(storage._resolve_browser_upload_host())
        self.assertEqual(host2, "https://upload-cn-east-2.qiniup.com")

    def test_uc_query_failure_falls_back_to_default(self):
        """UC 查询异常回退默认华东上传域名（此时直传可能 400，端点侧前端降级 multipart 兜底）"""
        import asyncio
        import utils.file_storage.qiniu_storage as qiniu_mod

        storage = self._make_storage()

        class _BoomClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                raise RuntimeError("uc down")

            async def __aexit__(self, *exc):
                return False

        with patch('utils.file_storage.qiniu_storage.httpx.AsyncClient', _BoomClient):
            host = asyncio.run(storage._resolve_browser_upload_host())
        self.assertEqual(host, qiniu_mod.QiniuFileStorage.DEFAULT_BROWSER_UPLOAD_HOST)



if __name__ == '__main__':
    unittest.main()
