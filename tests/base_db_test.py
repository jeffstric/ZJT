"""
数据库测试基类
提供数据库测试的基础设施，包括事务隔离、测试数据管理
"""
import unittest
import logging
from typing import List, Dict, Any
from .db_test_config import get_test_db_connection, TEST_DB_CONFIG

logger = logging.getLogger(__name__)


class DatabaseTestCase(unittest.TestCase):
    """
    数据库测试基类

    特性：
    1. setUpClass: 清空所有表数据（数据库由 Entrypoint 初始化）
    2. setUp: 开始事务
    3. tearDown: 清空所有表数据（保持数据库干净）
    """

    _db_initialized = False
    _connection = None

    @classmethod
    def setUpClass(cls):
        """测试类初始化：数据库已由 Entrypoint 初始化，这里只清空数据"""
        if not cls._db_initialized:
            logger.info(f"初始化测试数据库: {TEST_DB_CONFIG['database']}")
            cls._clear_all_tables()
            cls._db_initialized = True

    @classmethod
    def _clear_all_tables(cls):
        """清空所有表的数据（保留表结构）"""
        import pymysql

        conn = pymysql.connect(
            host=TEST_DB_CONFIG['host'],
            port=TEST_DB_CONFIG['port'],
            user=TEST_DB_CONFIG['user'],
            password=TEST_DB_CONFIG['password'],
            database=TEST_DB_CONFIG['database'],
            charset=TEST_DB_CONFIG['charset']
        )
        try:
            cursor = conn.cursor()
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            cursor.execute("SHOW TABLES")
            # SHOW TABLES 返回 [(table_name,), ...]
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                if table != 'alembic_version':
                    cursor.execute(f"TRUNCATE TABLE `{table}`")
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            conn.commit()
            logger.info(f"清空了 {len(tables)} 个表的数据")
        finally:
            conn.close()

    def setUp(self):
        """每个测试用例开始前：开启事务"""
        import pymysql
        from pymysql.cursors import DictCursor
        
        self._connection = pymysql.connect(
            host=TEST_DB_CONFIG['host'],
            port=TEST_DB_CONFIG['port'],
            user=TEST_DB_CONFIG['user'],
            password=TEST_DB_CONFIG['password'],
            database=TEST_DB_CONFIG['database'],
            charset=TEST_DB_CONFIG['charset'],
            cursorclass=DictCursor,
            autocommit=False
        )
        self._cursor = self._connection.cursor()
        logger.debug("开始事务")
    
    def tearDown(self):
        """每个测试用例结束后：回滚事务"""
        if self._connection:
            try:
                self._connection.rollback()
                logger.debug("回滚事务")
            except Exception as e:
                logger.warning(f"回滚事务失败: {e}")
            finally:
                try:
                    self._connection.close()
                except Exception as e:
                    logger.warning(f"关闭连接失败: {e}")
                self._connection = None
                self._cursor = None
    
    def execute_query(self, sql: str, params=None) -> List[Dict[str, Any]]:
        """
        执行查询语句
        
        Args:
            sql: SQL 查询语句
            params: 查询参数
            
        Returns:
            查询结果列表
        """
        self._cursor.execute(sql, params or ())
        return self._cursor.fetchall()
    
    def execute_update(self, sql: str, params=None) -> int:
        """
        执行更新语句（INSERT/UPDATE/DELETE）
        
        Args:
            sql: SQL 更新语句
            params: 更新参数
            
        Returns:
            影响的行数
        """
        affected_rows = self._cursor.execute(sql, params or ())
        return affected_rows
    
    def execute_insert(self, sql: str, params=None) -> int:
        """
        执行插入语句并返回插入的 ID
        
        Args:
            sql: SQL 插入语句
            params: 插入参数
            
        Returns:
            最后插入的 ID
        """
        self._cursor.execute(sql, params or ())
        return self._cursor.lastrowid
    
    def insert_fixture(self, table: str, data: Dict[str, Any]) -> int:
        """
        插入测试数据
        
        Args:
            table: 表名
            data: 数据字典
            
        Returns:
            插入的 ID
        """
        columns = ', '.join(f'`{k}`' for k in data.keys())
        placeholders = ', '.join(['%s'] * len(data))
        sql = f"INSERT INTO `{table}` ({columns}) VALUES ({placeholders})"
        return self.execute_insert(sql, tuple(data.values()))
    
    def clear_table(self, table: str):
        """
        清空表数据
        
        Args:
            table: 表名
        """
        self.execute_update(f"DELETE FROM `{table}`")
        logger.debug(f"清空表: {table}")
    
    def count_rows(self, table: str, where: str = None, params=None) -> int:
        """
        统计表行数
        
        Args:
            table: 表名
            where: WHERE 条件
            params: 条件参数
            
        Returns:
            行数
        """
        sql = f"SELECT COUNT(*) as count FROM `{table}`"
        if where:
            sql += f" WHERE {where}"
        result = self.execute_query(sql, params)
        return result[0]['count'] if result else 0
