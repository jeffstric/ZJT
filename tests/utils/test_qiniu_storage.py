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


if __name__ == '__main__':
    unittest.main()
