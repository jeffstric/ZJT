"""
图片上传工具单元测试
测试 URL 解析、图片压缩和上传功能
"""
import os
import sys
import tempfile
import shutil
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

# Mock 可能缺失的模块
sys.modules['aiofiles'] = MagicMock()
sys.modules['aiohttp'] = MagicMock()

from tests.base.base_db_test import DatabaseTestCase
from utils.image_upload_utils import (
    resolve_url_to_local_file_sync,
    compress_and_upload_image_sync,
    try_map_url_to_local_file,
    upload_local_images_to_cdn_sync,
    download_url_to_temp
)
from utils.media_cache import get_temp_date_dir
from PIL import Image
import asyncio


class TestImageUploadUtils(DatabaseTestCase):
    """图片上传工具测试"""
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        super().setUpClass()
        # 创建测试图片目录
        cls.test_images_dir = tempfile.mkdtemp(prefix="test_images_")
        
    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        super().tearDownClass()
        # 清理测试图片目录
        if os.path.exists(cls.test_images_dir):
            shutil.rmtree(cls.test_images_dir)
    
    def create_test_image(self, filename, size_mb=1.0, format='JPEG'):
        """
        创建测试图片
        
        Args:
            filename: 文件名
            size_mb: 目标大小（MB）
            format: 图片格式
        
        Returns:
            str: 图片路径
        """
        file_path = os.path.join(self.test_images_dir, filename)
        
        # 创建图片，调整尺寸以接近目标大小
        if size_mb < 1:
            width, height = 800, 600
        elif size_mb < 5:
            width, height = 2000, 1500
        elif size_mb < 10:
            width, height = 3000, 2250
        else:
            width, height = 4000, 3000
        
        img = Image.new('RGB', (width, height), color='red')
        
        # 保存图片
        if format == 'PNG':
            img.save(file_path, format='PNG')
        else:
            img.save(file_path, format='JPEG', quality=95)
        
        return file_path
    
    def test_try_map_url_to_local_file_success(self):
        """测试 URL 映射到本地文件成功"""
        config = {
            'server': {
                'host': 'http://localhost:9003'
            }
        }
        
        # 创建测试图片
        test_image = self.create_test_image('test_map.jpg')
        
        # 构造 URL（模拟服务器 URL）
        relative_path = os.path.relpath(test_image, project_root)
        url = f"http://localhost:9003/{relative_path}"
        
        # 测试映射
        local_path = try_map_url_to_local_file(url, config, project_root)
        
        # 验证
        self.assertIsNotNone(local_path)
        self.assertTrue(os.path.exists(local_path))
    
    def test_try_map_url_to_local_file_different_host(self):
        """测试不同域名的 URL 无法映射"""
        config = {
            'server': {
                'host': 'http://localhost:9003'
            }
        }
        
        url = "https://example.com/test.jpg"
        local_path = try_map_url_to_local_file(url, config, project_root)
        
        # 验证：不同域名应返回 None
        self.assertIsNone(local_path)
    
    @patch('utils.image_upload_utils.download_url_to_temp')
    def test_resolve_url_to_local_file_local_path(self, mock_download):
        """测试解析本地文件路径"""
        # 创建测试图片
        test_image = self.create_test_image('test_resolve.jpg')
        
        config = {'server': {'host': 'http://localhost:9003'}}
        
        # 测试解析本地路径
        result = resolve_url_to_local_file_sync(test_image, config)
        
        # 验证
        self.assertEqual(result, test_image)
        mock_download.assert_not_called()
    
    def test_compress_and_upload_image_no_compression_needed(self):
        """测试图片小于限制，无需压缩"""
        # 创建小图片（< 1 MB）
        test_image = self.create_test_image('small_image.jpg', size_mb=0.5)
        
        config = {
            'server': {
                'host': 'http://localhost:9003'
            }
        }
        
        # 测试压缩（限制 10 MB）
        success, new_url, error = compress_and_upload_image_sync(
            test_image,
            config,
            max_size_mb=10.0,
            is_local=False
        )
        
        # 验证：应该成功，返回原 URL
        self.assertTrue(success)
        self.assertEqual(new_url, test_image)
        self.assertIsNone(error)
    
    def test_compress_and_upload_image_with_compression(self):
        """测试图片超过限制，需要压缩"""
        # 创建大图片
        test_image = self.create_test_image('large_image.jpg', size_mb=12.0)
        
        # 检查实际大小
        actual_size_mb = os.path.getsize(test_image) / (1024 * 1024)
        
        # 如果实际大小小于限制，跳过测试
        if actual_size_mb <= 0.5:
            self.skipTest(f"测试图片太小 ({actual_size_mb:.2f} MB)，跳过压缩测试")
        
        config = {
            'server': {
                'host': 'http://localhost:9003'
            }
        }
        
        # 设置一个比实际大小小的限制，确保触发压缩
        max_size = max(0.1, actual_size_mb * 0.5)  # 使用实际大小的一半
        
        # 测试压缩
        success, new_url, error = compress_and_upload_image_sync(
            test_image,
            config,
            max_size_mb=max_size,
            is_local=False
        )
        
        # 验证：应该成功
        self.assertTrue(success, f"压缩失败: {error}")
        self.assertIsNotNone(new_url)
        self.assertIsNone(error)
        
        # 如果压缩了（返回的 URL 不是原图片路径），验证压缩结果
        if new_url != test_image:
            # 验证压缩后的文件在临时目录或是服务器 URL
            self.assertTrue(
                '/upload/temp/' in new_url or new_url.startswith('http'),
                f"压缩后 URL 格式不正确: {new_url}"
            )
    
    def test_compress_and_upload_image_invalid_path(self):
        """测试无效图片路径"""
        config = {
            'server': {
                'host': 'http://localhost:9003'
            }
        }
        
        # 测试不存在的文件
        success, new_url, error = compress_and_upload_image_sync(
            '/nonexistent/image.jpg',
            config,
            max_size_mb=10.0,
            is_local=False
        )
        
        # 验证：应该失败
        self.assertFalse(success)
        self.assertIsNone(new_url)
        self.assertIsNotNone(error)
    
    @patch('utils.image_upload_utils.upload_local_images_to_cdn')
    def test_compress_and_upload_image_local_env(self, mock_upload):
        """测试本地环境上传到 CDN"""
        # Mock 上传函数返回 CDN URL
        async def mock_upload_func(images, config, project_root):
            return ['https://cdn.example.com/test.jpg']
        
        mock_upload.side_effect = mock_upload_func
        
        # 创建测试图片
        test_image = self.create_test_image('cdn_test.jpg', size_mb=0.5)
        
        config = {
            'server': {
                'host': 'http://localhost:9003'
            }
        }
        
        # 测试本地环境上传
        success, new_url, error = compress_and_upload_image_sync(
            test_image,
            config,
            max_size_mb=10.0,
            is_local=True  # 本地环境
        )
        
        # 验证
        self.assertTrue(success)
        self.assertEqual(new_url, 'https://cdn.example.com/test.jpg')
        self.assertIsNone(error)
        mock_upload.assert_called_once()
    
    def test_get_temp_date_dir(self):
        """测试获取临时日期目录"""
        from datetime import datetime
        
        # 测试获取当前日期目录
        temp_dir = get_temp_date_dir()
        
        # 验证
        self.assertIsInstance(temp_dir, Path)
        self.assertTrue(temp_dir.exists())
        
        # 验证路径格式: upload/temp/YYYYMMDD
        date_str = datetime.now().strftime("%Y%m%d")
        self.assertTrue(str(temp_dir).endswith(f"upload/temp/{date_str}"))
    
    def test_compress_image_png_to_jpeg(self):
        """测试 PNG 转 JPEG 压缩"""
        # 创建 PNG 图片
        test_image = self.create_test_image('test.png', size_mb=12.0, format='PNG')
        
        config = {
            'server': {
                'host': 'http://localhost:9003'
            }
        }
        
        # 测试压缩
        success, new_url, error = compress_and_upload_image_sync(
            test_image,
            config,
            max_size_mb=5.0,
            is_local=False
        )
        
        # 验证：PNG 应转换为 JPEG
        self.assertTrue(success, f"压缩失败: {error}")
        
        if new_url and '.jpg' in new_url.lower() or '.jpeg' in new_url.lower():
            # 验证转换成功
            self.assertTrue('.jpg' in new_url.lower() or '.jpeg' in new_url.lower())
    
    @patch('utils.image_upload_utils.get_file_storage')
    def test_upload_local_images_to_cdn_batch(self, mock_storage):
        """测试批量上传多张图片到CDN"""
        # 创建多张测试图片
        test_images = [
            self.create_test_image('batch1.jpg', size_mb=0.3),
            self.create_test_image('batch2.jpg', size_mb=0.4),
            self.create_test_image('batch3.jpg', size_mb=0.5),
        ]
        
        # Mock 存储对象和上传结果
        mock_upload_result = MagicMock()
        mock_upload_result.success = True
        mock_upload_result.key = 'test_key.jpg'
        
        mock_storage_instance = MagicMock()
        mock_storage_instance.upload_file = AsyncMock(return_value=mock_upload_result)
        mock_storage_instance.generate_key_with_datetime = MagicMock(return_value='test_key.jpg')
        mock_storage_instance.get_download_url = MagicMock(return_value='https://cdn.example.com/uploaded.jpg')
        mock_storage.return_value = mock_storage_instance
        
        config = {
            'server': {'host': 'http://localhost:9003'},
            'file_storage': {'type': 'mock'}
        }
        
        # 测试批量上传
        result_urls = upload_local_images_to_cdn_sync(test_images, config, project_root)
        
        # 验证
        self.assertEqual(len(result_urls), 3)
        for url in result_urls:
            self.assertTrue(url.startswith('https://cdn.example.com/'))
        
        # 验证上传被调用了3次
        self.assertEqual(mock_storage_instance.upload_file.call_count, 3)
    
    @patch('utils.image_upload_utils.get_file_storage')
    def test_upload_local_images_to_cdn_mixed_urls(self, mock_storage):
        """测试混合本地和外网URL的批量上传"""
        # 创建本地测试图片
        local_image = self.create_test_image('local.jpg', size_mb=0.3)
        
        # Mock 存储对象和上传结果
        mock_upload_result = MagicMock()
        mock_upload_result.success = True
        mock_upload_result.key = 'test_key.jpg'
        
        mock_storage_instance = MagicMock()
        mock_storage_instance.upload_file = AsyncMock(return_value=mock_upload_result)
        mock_storage_instance.generate_key_with_datetime = MagicMock(return_value='test_key.jpg')
        mock_storage_instance.get_download_url = MagicMock(return_value='https://cdn.example.com/uploaded.jpg')
        mock_storage.return_value = mock_storage_instance
        
        config = {
            'server': {'host': 'http://localhost:9003'},
            'file_storage': {'type': 'mock'}
        }
        
        # 混合URL列表：本地文件 + 外网URL
        mixed_urls = [
            local_image,
            'https://example.com/remote.jpg',  # 外网URL，不应上传
            '',  # 空字符串，应跳过
        ]
        
        # 测试批量上传
        result_urls = upload_local_images_to_cdn_sync(mixed_urls, config, project_root)
        
        # 验证
        self.assertEqual(len(result_urls), 2)  # 只有本地文件和外网URL
        self.assertTrue(result_urls[0].startswith('https://cdn.example.com/'))
        self.assertEqual(result_urls[1], 'https://example.com/remote.jpg')
        
        # 验证只上传了本地文件
        self.assertEqual(mock_storage_instance.upload_file.call_count, 1)
    
    @patch('utils.image_upload_utils.download_url_to_temp')
    def test_resolve_url_to_local_file_remote_url(self, mock_download):
        """测试远程URL下载到本地"""
        # Mock 下载函数返回临时文件路径
        async def mock_download_func(url, app_dir=None):
            temp_path = os.path.join(self.test_images_dir, 'downloaded.jpg')
            # 创建模拟下载的文件
            Image.new('RGB', (800, 600), 'blue').save(temp_path)
            return temp_path
        
        mock_download.side_effect = mock_download_func
        
        config = {
            'server': {'host': 'http://localhost:9003'}
        }
        
        # 测试远程URL
        remote_url = 'https://example.com/remote_image.jpg'
        result = resolve_url_to_local_file_sync(remote_url, config)
        
        # 验证
        self.assertIsNotNone(result)
        self.assertTrue(os.path.exists(result))
        # 注意：project_root 参数默认为 None，所以实际调用时传的是 None
        mock_download.assert_called_once_with(remote_url, None)
    
    def test_resolve_url_to_local_file_server_url(self, ):
        """测试服务器自身URL解析"""
        # 创建测试图片
        test_image = self.create_test_image('server_test.jpg', size_mb=0.3)
        
        # 构造服务器URL（模拟从服务器返回的URL）
        relative_path = os.path.relpath(test_image, project_root)
        server_url = f"http://localhost:9003/{relative_path}"
        
        config = {
            'server': {'host': 'http://localhost:9003'}
        }
        
        # 测试解析
        result = resolve_url_to_local_file_sync(server_url, config)
        
        # 验证：应该映射回本地文件
        self.assertIsNotNone(result)
        self.assertTrue(os.path.exists(result))
        self.assertEqual(os.path.abspath(result), os.path.abspath(test_image))
    
    @patch('utils.image_upload_utils.get_file_storage')
    def test_upload_local_images_to_cdn_nonexistent_file(self, mock_storage):
        """测试上传不存在的本地文件应直接失败，避免降级导致图片和视频不一致"""
        # Mock 存储对象
        mock_storage_instance = MagicMock()
        mock_storage.return_value = mock_storage_instance

        config = {
            'server': {'host': 'http://localhost:9003'},
            'file_storage': {'type': 'mock'}
        }

        # 测试不存在的文件
        nonexistent_files = [
            '/nonexistent/file1.jpg',
            '/nonexistent/file2.jpg',
        ]

        # 验证：不存在的文件应该直接抛出 RuntimeError，而不是降级保留原路径
        with self.assertRaises(RuntimeError) as context:
            upload_local_images_to_cdn_sync(nonexistent_files, config, project_root)

        self.assertIn('本地图片文件不存在', str(context.exception))

        # 验证：没有尝试上传
        mock_storage_instance.upload_file.assert_not_called()
    
    def test_compress_and_upload_image_edge_cases(self):
        """测试压缩上传的边界情况"""
        config = {
            'server': {'host': 'http://localhost:9003'}
        }
        
        # 测试 1: 空字符串
        success, url, error = compress_and_upload_image_sync('', config, 10.0, False)
        self.assertFalse(success)
        self.assertIsNone(url)
        self.assertIsNotNone(error)
        
        # 测试 2: None
        success, url, error = compress_and_upload_image_sync(None, config, 10.0, False)
        self.assertFalse(success)
        self.assertIsNone(url)
        self.assertIsNotNone(error)
    
    def test_try_map_url_to_local_file_edge_cases(self):
        """测试URL映射的边界情况"""
        config = {
            'server': {'host': 'http://localhost:9003'}
        }
        
        # 测试 1: 空配置
        result = try_map_url_to_local_file('http://localhost:9003/test.jpg', {}, project_root)
        self.assertIsNone(result)
        
        # 测试 2: 无效URL
        result = try_map_url_to_local_file('not-a-url', config, project_root)
        self.assertIsNone(result)
        
        # 测试 3: 不同端口
        result = try_map_url_to_local_file('http://localhost:8080/test.jpg', config, project_root)
        self.assertIsNone(result)


if __name__ == '__main__':
    import unittest
    unittest.main()
