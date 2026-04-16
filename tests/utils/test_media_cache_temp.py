"""
媒体缓存临时目录清理测试
测试 temp 目录清理功能
"""
import os
import sys
import tempfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path

# 添加项目根目录到路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.insert(0, project_root)

# Mock 可能缺失的模块
from unittest.mock import MagicMock
sys.modules['aiohttp'] = MagicMock()
sys.modules['aiofiles'] = MagicMock()

from tests.base.base_db_test import DatabaseTestCase
from utils.media_cache import MediaCacheManager, get_temp_date_dir


class TestMediaCacheTempCleanup(DatabaseTestCase):
    """媒体缓存临时目录清理测试"""
    
    def setUp(self):
        """测试前准备"""
        super().setUp()
        self.cache_manager = MediaCacheManager()
        # 确保 temp 目录存在
        self.temp_base_dir = self.cache_manager.root_dir / "upload" / "temp"
        self.temp_base_dir.mkdir(parents=True, exist_ok=True)
    
    def create_temp_date_dir_with_files(self, days_ago, file_count=3):
        """
        创建指定天数前的临时目录并添加测试文件
        
        Args:
            days_ago: 多少天前
            file_count: 创建文件数量
        
        Returns:
            Path: 创建的目录路径
        """
        target_date = datetime.now() - timedelta(days=days_ago)
        date_str = target_date.strftime("%Y%m%d")
        
        date_dir = self.temp_base_dir / date_str
        date_dir.mkdir(parents=True, exist_ok=True)
        
        # 创建测试文件
        for i in range(file_count):
            test_file = date_dir / f"test_file_{i}.txt"
            test_file.write_text(f"Test content {i}")
        
        return date_dir
    
    def test_get_temp_date_dir(self):
        """测试获取临时日期目录"""
        # 测试获取当前日期目录
        temp_dir = get_temp_date_dir()
        
        # 验证
        self.assertIsInstance(temp_dir, Path)
        self.assertTrue(temp_dir.exists())
        
        # 验证路径格式
        date_str = datetime.now().strftime("%Y%m%d")
        self.assertTrue(str(temp_dir).endswith(f"upload/temp/{date_str}"))
    
    def test_get_temp_date_dir_specific_date(self):
        """测试获取指定日期的临时目录"""
        target_date = datetime(2026, 3, 15)
        temp_dir = get_temp_date_dir(target_date)
        
        # 验证
        self.assertTrue(temp_dir.exists())
        self.assertTrue(str(temp_dir).endswith("upload/temp/20260315"))
    
    def test_cleanup_temp_dir_no_old_files(self):
        """测试清理临时目录 - 没有过期文件"""
        # 创建今天的文件
        today_dir = self.create_temp_date_dir_with_files(0, file_count=2)
        
        # 执行清理（保留 2 天）
        deleted_count = self.cache_manager.cleanup_temp_dir(max_days=2)
        
        # 验证：今天的文件不应被删除
        self.assertEqual(deleted_count, 0)
        self.assertTrue(today_dir.exists())
    
    def test_cleanup_temp_dir_with_old_files(self):
        """测试清理临时目录 - 有过期文件"""
        # 创建 3 天前的文件（应被删除）
        old_dir = self.create_temp_date_dir_with_files(3, file_count=5)
        
        # 创建今天的文件（不应被删除）
        today_dir = self.create_temp_date_dir_with_files(0, file_count=2)
        
        # 执行清理（保留 2 天）
        deleted_count = self.cache_manager.cleanup_temp_dir(max_days=2)
        
        # 验证：3 天前的文件应被删除
        self.assertEqual(deleted_count, 5)
        self.assertFalse(old_dir.exists())
        
        # 验证：今天的文件不应被删除
        self.assertTrue(today_dir.exists())
    
    def test_cleanup_temp_dir_multiple_old_dirs(self):
        """测试清理临时目录 - 多个过期目录"""
        # 创建多个过期目录
        dir_3_days = self.create_temp_date_dir_with_files(3, file_count=3)
        dir_5_days = self.create_temp_date_dir_with_files(5, file_count=4)
        dir_10_days = self.create_temp_date_dir_with_files(10, file_count=2)
        
        # 创建未过期目录
        dir_1_day = self.create_temp_date_dir_with_files(1, file_count=5)
        
        # 执行清理（保留 2 天）
        deleted_count = self.cache_manager.cleanup_temp_dir(max_days=2)
        
        # 验证：所有过期目录应被删除
        self.assertEqual(deleted_count, 3 + 4 + 2)
        self.assertFalse(dir_3_days.exists())
        self.assertFalse(dir_5_days.exists())
        self.assertFalse(dir_10_days.exists())
        
        # 验证：未过期目录保留
        self.assertTrue(dir_1_day.exists())
    
    def test_cleanup_temp_dir_nonexistent_directory(self):
        """测试清理不存在的临时目录"""
        # 删除 temp 目录
        if self.temp_base_dir.exists():
            shutil.rmtree(self.temp_base_dir)
        
        # 执行清理
        deleted_count = self.cache_manager.cleanup_temp_dir(max_days=2)
        
        # 验证：应返回 0
        self.assertEqual(deleted_count, 0)
    
    def test_cleanup_all_includes_temp(self):
        """测试 cleanup_all 包含 temp 目录清理"""
        # 创建过期的 temp 文件
        old_dir = self.create_temp_date_dir_with_files(5, file_count=3)
        
        # 执行完整清理
        result = self.cache_manager.cleanup_all()
        
        # 验证：结果包含 temp_deleted
        self.assertIn('temp_deleted', result)
        self.assertGreaterEqual(result['temp_deleted'], 3)
        
        # 验证：过期目录已删除
        self.assertFalse(old_dir.exists())
    
    def test_cleanup_temp_dir_with_invalid_dir_names(self):
        """测试清理包含无效目录名的 temp 目录"""
        # 创建有效的日期目录
        valid_dir = self.create_temp_date_dir_with_files(5, file_count=2)
        
        # 创建无效目录名（非日期格式）
        invalid_dir = self.temp_base_dir / "invalid_dir"
        invalid_dir.mkdir(parents=True, exist_ok=True)
        invalid_file = invalid_dir / "test.txt"
        invalid_file.write_text("test")
        
        # 执行清理
        deleted_count = self.cache_manager.cleanup_temp_dir(max_days=2)
        
        # 验证：只删除有效日期格式的过期目录
        self.assertEqual(deleted_count, 2)
        self.assertFalse(valid_dir.exists())
        
        # 验证：无效目录名的目录不被删除
        self.assertTrue(invalid_dir.exists())
        
        # 清理测试创建的无效目录
        shutil.rmtree(invalid_dir)


if __name__ == '__main__':
    import unittest
    unittest.main()
