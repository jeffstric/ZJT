"""
数据库测试基类
提供数据库测试的基础设施，包括事务隔离、测试数据管理
"""
import unittest
import logging
import os
from typing import List, Dict, Any
from .db_test_config import get_test_db_connection, TEST_DB_CONFIG

logger = logging.getLogger(__name__)


def _check_and_initialize_database():
    """
    检查并初始化测试数据库。

    流程：
    1. 如果 alembic_version 表不存在，说明数据库从未初始化
       - 导入 baseline.sql 创建所有基线表（含 alembic_version 及版本号）
    2. 导入后 alembic_version 表必然存在，执行 alembic upgrade head 完成增量迁移
    3. 如果 alembic_version 表已存在且有版本记录，直接执行 alembic upgrade head
    """
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

        # 检查 alembic_version 表是否存在
        cursor.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = 'alembic_version'
        """, (TEST_DB_CONFIG['database'],))
        table_exists = cursor.fetchone()[0] > 0

        if not table_exists:
            # 数据库从未初始化，导入 baseline.sql 创建所有基线表
            logger.warning(
                f"测试数据库 '{TEST_DB_CONFIG['database']}' 未初始化，"
                f"将导入 baseline.sql 创建基线表..."
            )
            _import_baseline_sql(conn)

        # 运行 alembic 迁移（baseline.sql 已包含基线版本号，增量迁移会自动执行）
        _run_alembic_migrations()
    finally:
        conn.close()


def _drop_all_tables(conn):
    """
    删除数据库中所有现有表。
    关闭外键检查后按逆序删除，避免因外键约束导致删除失败。
    """
    cursor = conn.cursor()
    cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]
    for table in tables:
        cursor.execute(f"DROP TABLE IF EXISTS `{table}`")
    cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
    conn.commit()
    if tables:
        logger.info(f"已删除 {len(tables)} 个现有表: {', '.join(tables)}")


def _import_baseline_sql(conn):
    """
    导入 baseline.sql 初始化数据库。
    baseline.sql 包含所有基线表的创建语句及 alembic_version 版本号，
    导入后数据库即处于基线版本状态，后续由 alembic upgrade head 执行增量迁移。
    """
    # 先清空所有现有表，避免残留表导致外键冲突
    _drop_all_tables(conn)

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    baseline_path = os.path.join(project_root, 'model', 'sql', 'baseline.sql')

    logger.info(f"baseline.sql 路径: {baseline_path}")

    if not os.path.exists(baseline_path):
        raise FileNotFoundError(f"baseline.sql 不存在: {baseline_path}")

    with open(baseline_path, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    logger.info(f"baseline.sql 文件大小: {len(sql_content)} 字节")

    cursor = conn.cursor()
    # baseline.sql 中包含多条语句，逐条执行
    # 过滤掉 MySQL dump 的条件注释（/*!...*/;）和空语句
    statements = []
    for stmt in sql_content.split(';'):
        stmt = stmt.strip()
        if not stmt:
            continue
        # 保留 /*!...*/ 形式的条件执行语句，MySQL 会正常执行
        statements.append(stmt)

    logger.info(f"解析出 {len(statements)} 条 SQL 语句")

    success_count = 0
    error_count = 0
    for i, stmt in enumerate(statements):
        try:
            cursor.execute(stmt)
            success_count += 1
            # 只对 CREATE TABLE / INSERT 等关键语句打印日志
            stmt_upper = stmt.upper().lstrip()
            if stmt_upper.startswith(('CREATE TABLE', 'DROP TABLE', 'INSERT INTO')):
                # 提取表名用于日志
                table_hint = stmt[:100].replace('\n', ' ')
                logger.info(f"  [{i+1}/{len(statements)}] 成功: {table_hint}...")
        except Exception as e:
            error_count += 1
            logger.warning(f"  [{i+1}/{len(statements)}] 失败（已跳过）: {e}\n  语句: {stmt[:200]}...")

    conn.commit()
    logger.info(f"baseline.sql 导入完成: 成功 {success_count}, 失败 {error_count}, 总计 {len(statements)}")

    # 验证：列出导入后的所有表
    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]
    logger.info(f"导入后数据库表列表 ({len(tables)}): {', '.join(tables)}")

    # 验证 alembic_version 版本号
    cursor.execute("SELECT version_num FROM alembic_version")
    versions = [row[0] for row in cursor.fetchall()]
    logger.info(f"alembic_version 版本号: {versions}")


def _run_alembic_migrations():
    """
    运行 alembic 迁移。

    通过环境变量将测试数据库配置传递给 alembic 子进程，
    因为 alembic/env.py 从 model.database.DB_CONFIG 读取配置，
    而 DB_CONFIG 支持通过环境变量 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME 覆盖。
    """
    import subprocess

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    # 构建环境变量：继承当前环境 + 覆盖测试数据库配置
    env = os.environ.copy()
    env['DB_HOST'] = TEST_DB_CONFIG['host']
    env['DB_PORT'] = str(TEST_DB_CONFIG['port'])
    env['DB_USER'] = TEST_DB_CONFIG['user']
    env['DB_PASSWORD'] = TEST_DB_CONFIG['password']
    env['DB_NAME'] = TEST_DB_CONFIG['database']

    logger.info(
        f"运行 alembic upgrade head... (目标库: {TEST_DB_CONFIG['database']}@{TEST_DB_CONFIG['host']})"
    )
    result = subprocess.run(
        ['alembic', 'upgrade', 'head'],
        cwd=project_root,
        capture_output=True,
        text=True,
        env=env
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"alembic 迁移失败:\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )

    # 输出 alembic 的 stdout/stderr 以便调试
    if result.stdout.strip():
        for line in result.stdout.strip().split('\n'):
            logger.info(f"  alembic: {line}")
    if result.stderr.strip():
        for line in result.stderr.strip().split('\n'):
            logger.info(f"  alembic stderr: {line}")

    logger.info("alembic 迁移完成")


class DatabaseTestCase(unittest.TestCase):
    """
    数据库测试基类

    特性：
    1. setUpClass: 清空所有表数据（数据库由 Entrypoint 初始化）
    2. setUp: 开始事务
    3. tearDown: 清空所有表数据（保持数据库干净）

    重要说明 - 数据插入方法选择：
    
    1. 使用 insert_fixture() 的场景：
       - 测试只使用原始 SQL 查询（execute_query/execute_update）
       - 不需要调用 Model 层的方法（如 get_by_id()）
       - 示例：
         world_id = self.insert_fixture('world', {'name': '测试世界', 'user_id': 1})
         result = self.execute_query("SELECT * FROM world WHERE id = %s", (world_id,))
    
    2. 使用 Model 层 create() 方法的场景：
       - 测试需要调用 Model 层的方法（如 get_by_id(), update(), delete()）
       - 需要测试 Model 层的业务逻辑
       - 示例：
         from model.world import WorldModel
         world_id = WorldModel.create(name='测试世界', user_id=1)
         world = WorldModel.get_by_id(world_id)  # 能正确获取
    
    原因：
    - insert_fixture() 使用测试专用连接（self._connection），设置了 autocommit=False
    - Model 层使用 model/database.py 的连接池（另一个连接）
    - 两个连接在事务隔离下互相看不到对方未提交的数据
    - 如果用 insert_fixture() 插入数据，Model 层的 get_by_id() 会返回 None
    - 如果用 insert_fixture() 插入父表，Model 层插入子表时会因外键约束失败
    
    混合使用示例（推荐）：
        # 使用 Model 层创建依赖数据
        from model.world import WorldModel
        world_id = WorldModel.create(name='测试世界', user_id=1)
        
        # 使用 Model 层创建测试数据
        from model.character import CharacterModel
        character_id = CharacterModel.create(
            world_id=world_id,
            name='测试角色',
            user_id=1
        )
        
        # 使用 Model 层验证
        character = CharacterModel.get_by_id(character_id)
        self.assertIsNotNone(character)
    """

    _db_initialized = False
    _connection = None

    @classmethod
    def setUpClass(cls):
        """测试类初始化：检查迁移状态并清空数据"""
        if not cls._db_initialized:
            logger.info(f"初始化测试数据库: {TEST_DB_CONFIG['database']}")
            _check_and_initialize_database()
            cls._clear_all_tables()
            cls._db_initialized = True
        else:
            # 即使已初始化，也始终执行 alembic upgrade head 确保迁移完整（幂等操作）
            logger.info(f"数据库已初始化，执行 alembic upgrade head 确保迁移完整...")
            _run_alembic_migrations()
            cls._clear_all_tables()

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
        self._connection.commit()
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
