"""
数据库连接和初始化测试
测试数据库连接、建表等基础功能
"""
import unittest
from tests.base_db_test import DatabaseTestCase


class TestDatabaseConnection(DatabaseTestCase):
    """数据库连接和初始化测试"""
    
    def test_database_connection(self):
        """测试数据库连接"""
        self.assertIsNotNone(self._connection)
        self.assertIsNotNone(self._cursor)
    
    def test_ai_tools_table_exists(self):
        """测试 ai_tools 表是否存在"""
        result = self.execute_query(
            "SHOW TABLES LIKE 'ai_tools'"
        )
        self.assertEqual(len(result), 1)
    
    def test_world_table_exists(self):
        """测试 world 表是否存在"""
        result = self.execute_query(
            "SHOW TABLES LIKE 'world'"
        )
        self.assertEqual(len(result), 1)
    
    def test_tasks_table_exists(self):
        """测试 tasks 表是否存在"""
        result = self.execute_query(
            "SHOW TABLES LIKE 'tasks'"
        )
        self.assertEqual(len(result), 1)
    
    def test_ai_audio_table_exists(self):
        """测试 ai_audio 表是否存在"""
        result = self.execute_query(
            "SHOW TABLES LIKE 'ai_audio'"
        )
        self.assertEqual(len(result), 1)
    
    def test_payment_orders_table_exists(self):
        """测试 payment_orders 表是否存在"""
        result = self.execute_query(
            "SHOW TABLES LIKE 'payment_orders'"
        )
        self.assertEqual(len(result), 1)
    
    def test_database_charset(self):
        """测试数据库字符集"""
        result = self.execute_query(
            "SELECT DEFAULT_CHARACTER_SET_NAME FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = DATABASE()"
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['DEFAULT_CHARACTER_SET_NAME'], 'utf8mb4')


if __name__ == '__main__':
    unittest.main()
