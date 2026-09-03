"""
project_path 单元测试

测试上传路径工具函数的纯逻辑方法。
不使用 mock，直接测试实际函数。
"""
import os
import unittest
from datetime import datetime


class TestGetUploadDir(unittest.TestCase):
    """测试 get_upload_dir()"""

    def test_returns_string(self):
        """返回字符串类型的路径"""
        from utils.project_path import get_upload_dir
        result = get_upload_dir()
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)

    def test_contains_upload(self):
        """路径包含 upload 目录"""
        from utils.project_path import get_upload_dir
        result = get_upload_dir()
        self.assertIn('upload', result.lower())


class TestGetUploadSubdir(unittest.TestCase):
    """测试 get_upload_subdir()"""

    def test_single_part(self):
        """单级子目录"""
        from utils.project_path import get_upload_subdir
        result = get_upload_subdir('temp', ensure=False)
        self.assertTrue(result.endswith(os.path.join('upload', 'temp')) or
                        result.endswith(os.path.join('upload', 'temp/')))

    def test_multiple_parts(self):
        """多级子目录"""
        from utils.project_path import get_upload_subdir
        result = get_upload_subdir('temp', '20250501', ensure=False)
        self.assertIn('temp', result)
        self.assertIn('20250501', result)


class TestGetUploadTempDir(unittest.TestCase):
    """测试 get_upload_temp_dir()"""

    def test_default_date(self):
        """默认使用当天日期"""
        from utils.project_path import get_upload_temp_dir
        result = get_upload_temp_dir()
        today = datetime.now().strftime("%Y%m%d")
        self.assertIn(today, result)

    def test_custom_date(self):
        """指定日期"""
        from utils.project_path import get_upload_temp_dir
        result = get_upload_temp_dir('20250601')
        self.assertIn('20250601', result)


class TestGenerateUploadFilename(unittest.TestCase):
    """测试 generate_upload_filename()"""

    def test_default_params(self):
        """默认参数生成文件名"""
        from utils.project_path import generate_upload_filename
        result = generate_upload_filename()

        self.assertTrue(result.filename.startswith('upload_'))
        self.assertTrue(result.filename.endswith('.bin'))
        self.assertEqual(len(result.unique_id), 8)
        self.assertTrue(len(result.timestamp) > 0)

    def test_custom_prefix_and_extension(self):
        """自定义前缀和扩展名"""
        from utils.project_path import generate_upload_filename
        result = generate_upload_filename(prefix='media', extension='.png')

        self.assertTrue(result.filename.startswith('media_'))
        self.assertTrue(result.filename.endswith('.png'))

    def test_unique_id_length(self):
        """自定义 UUID 长度"""
        from utils.project_path import generate_upload_filename
        result = generate_upload_filename(unique_id_len=12)

        self.assertEqual(len(result.unique_id), 12)


class TestBuildUploadUrl(unittest.TestCase):
    """测试 build_upload_url()"""

    def test_without_host(self):
        """不带 host 构建 URL"""
        from utils.project_path import build_upload_url
        result = build_upload_url('temp', '20250501', 'upload_xxx.png')
        self.assertEqual(result, '/upload/temp/20250501/upload_xxx.png')

    def test_with_host(self):
        """带 host 构建 URL"""
        from utils.project_path import build_upload_url
        result = build_upload_url('temp', '20250501', 'upload_xxx.png', host='https://example.com')
        self.assertEqual(result, 'https://example.com/upload/temp/20250501/upload_xxx.png')

    def test_host_with_trailing_slash(self):
        """host 末尾有斜杠"""
        from utils.project_path import build_upload_url
        result = build_upload_url('image.png', host='https://example.com/')
        self.assertEqual(result, 'https://example.com/upload/image.png')

    def test_parts_with_slashes(self):
        """路径段包含斜杠"""
        from utils.project_path import build_upload_url
        result = build_upload_url('/temp/', '/20250501/', '/upload_xxx.png')
        self.assertEqual(result, '/upload/temp/20250501/upload_xxx.png')


class TestResolveUploadUrlToLocalPath(unittest.TestCase):
    """测试 resolve_upload_url_to_local_path()"""

    def test_full_url(self):
        """完整 URL 解析"""
        from utils.project_path import resolve_upload_url_to_local_path
        result = resolve_upload_url_to_local_path('https://example.com/upload/temp/image.png')
        self.assertIn('temp', result)
        self.assertIn('image.png', result)

    def test_path_with_upload_prefix(self):
        """以 /upload/ 开头的路径"""
        from utils.project_path import resolve_upload_url_to_local_path
        result = resolve_upload_url_to_local_path('/upload/temp/image.png')
        self.assertIn('temp', result)
        self.assertIn('image.png', result)

    def test_relative_path(self):
        """相对于 upload/ 的路径"""
        from utils.project_path import resolve_upload_url_to_local_path
        result = resolve_upload_url_to_local_path('temp/image.png')
        self.assertIn('temp', result)
        self.assertIn('image.png', result)

    def test_returns_absolute_path(self):
        """返回绝对路径"""
        from utils.project_path import resolve_upload_url_to_local_path
        result = resolve_upload_url_to_local_path('temp/image.png')
        self.assertTrue(os.path.isabs(result))

    def test_rejects_parent_directory_traversal(self):
        from utils.project_path import resolve_upload_url_to_local_path
        with self.assertRaises(ValueError):
            resolve_upload_url_to_local_path('/upload/../config.yml')

    def test_rejects_encoded_parent_directory_traversal(self):
        from utils.project_path import resolve_upload_url_to_local_path
        with self.assertRaises(ValueError):
            resolve_upload_url_to_local_path('/upload/%2e%2e/config.yml')

    def test_rejects_windows_separator_traversal(self):
        from utils.project_path import resolve_upload_url_to_local_path
        with self.assertRaises(ValueError):
            resolve_upload_url_to_local_path(r'/upload/..\config.yml')


if __name__ == '__main__':
    unittest.main()
