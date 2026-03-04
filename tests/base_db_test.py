"""
数据库测试基类
提供数据库测试的基础设施，包括自动建表、事务隔离、测试数据管理
"""
import os
import unittest
import logging
from typing import List, Dict, Any
from .db_test_config import get_test_db_connection, TEST_DB_CONFIG

logger = logging.getLogger(__name__)


class DatabaseTestCase(unittest.TestCase):
    """
    数据库测试基类
    
    特性：
    1. setUpClass: 连接测试数据库，执行建表 SQL
    2. setUp: 开始事务
    3. tearDown: 回滚事务（保持数据库干净）
    4. tearDownClass: 清理连接
    """
    
    _db_initialized = False
    _connection = None
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化：创建数据库表结构"""
        if not cls._db_initialized:
            logger.info(f"初始化测试数据库: {TEST_DB_CONFIG['database']}")
            cls._init_database_schema()
            cls._db_initialized = True
    
    @classmethod
    def _init_database_schema(cls):
        """初始化数据库表结构"""
        sql_files = cls._get_sql_files_in_order()
        
        with get_test_db_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
            
            for sql_file in sql_files:
                logger.info(f"执行 SQL 文件: {sql_file}")
                cls._execute_sql_file(cursor, sql_file)
            
            cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
            conn.commit()
            logger.info("数据库表结构初始化完成")
    
    @classmethod
    def _get_sql_files_in_order(cls) -> List[str]:
        """
        按依赖顺序获取 SQL 文件列表
        
        Returns:
            SQL 文件路径列表
        """
        sql_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'model', 'sql'
        )
        
        ordered_files = [
            'world.sql',
            'character.sql',
            'location.sql',
            'props.sql',
            'script.sql',
            'video_workflow.sql',
            'ai_tools.sql',
            'runninghub_slots.sql',
            'ai_audio.sql',
            'payment_orders.sql',
            'tasks.sql',
        ]
        
        sql_files = []
        for filename in ordered_files:
            filepath = os.path.join(sql_dir, filename)
            if os.path.exists(filepath):
                sql_files.append(filepath)
            else:
                logger.warning(f"SQL 文件不存在: {filepath}")
        
        return sql_files
    
    @classmethod
    def _execute_sql_file(cls, cursor, sql_file: str):
        """
        执行 SQL 文件
        
        Args:
            cursor: 数据库游标
            sql_file: SQL 文件路径
        """
        with open(sql_file, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        
        lines = []
        for line in sql_content.split('\n'):
            line = line.strip()
            if line and not line.startswith('--'):
                lines.append(line)
        
        clean_sql = ' '.join(lines)
        statements = [s.strip() for s in clean_sql.split(';') if s.strip()]
        
        for statement in statements:
            if statement:
                try:
                    cursor.execute(statement)
                except Exception as e:
                    logger.error(f"执行 SQL 失败: {statement[:100]}... 错误: {e}")
                    raise
    
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
