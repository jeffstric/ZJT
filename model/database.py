"""
Database connection configuration
"""
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager
import os
import logging
import threading

logger = logging.getLogger(__name__)

# Load database configuration using unified config utility
from config.config_util import get_config_value
from config.constant import DB_POOL_CONNECT_TIMEOUT

DB_CONFIG = get_config_value('database', default={})
if not DB_CONFIG:
    raise ValueError("Database configuration not found in config file")

# Override with environment variables if set
DB_CONFIG['host'] = os.environ.get('DB_HOST', DB_CONFIG.get('host'))
DB_CONFIG['port'] = int(os.environ.get('DB_PORT', DB_CONFIG.get('port', 3306)))
DB_CONFIG['user'] = os.environ.get('DB_USER', DB_CONFIG.get('user'))
DB_CONFIG['password'] = os.environ.get('DB_PASSWORD', DB_CONFIG.get('password'))
DB_CONFIG['database'] = os.environ.get('DB_NAME', DB_CONFIG.get('database'))

# Ensure charset is set
if 'charset' not in DB_CONFIG:
    DB_CONFIG['charset'] = 'utf8mb4'


# ===== 数据库连接池（8·1 端口耗尽事故修复）=====
# 背景：原实现每次查询 pymysql.connect() + close()（短连接），高并发下客户端临时端口
# 被 TIME_WAIT 占满（Errno 99 Cannot assign requested address），导致全站 DB 雪崩。
# 详见 docs/backend/incidents/2026-08-01-db-port-exhaustion.md
# 改造：用 DBUtils.PooledDB 复用连接，连接创建速率从「每查询一次」降为「稳态≈0」。
# 详见 docs/backend/database_connection_pool.md
from dbutils.pooled_db import PooledDB

_pool = None          # 模块级池单例，惰性创建
_pool_pid = None      # 记录建池时的 pid，用于 fork 后检测进程漂移、重建池
_pool_lock = threading.Lock()


def _get_pool():
    """懒加载连接池单例，fork 安全（机制保证，非仅靠注释论证）。

    多进程模型（run_prod.py 拉起 scheduler + gunicorn 4 worker + N 个
    script_split_worker）下，每个进程各自独立建池、互不共享。

    fork 安全机制：每次取池时比对 os.getpid()。
    - 正常情况（gunicorn 无 --preload）：每 worker fork 后首次调用才建池，
      pid 各异、天然隔离。
    - 防御性：即使将来误加 --preload 且模块级触发了 DB 调用，master 进程建了池，
      fork 出的子进程 pid 与建池 pid 不同 → 此处检测到漂移 → 丢弃旧池重建，
      绝不跨进程共享 MySQL 的 TCP socket 句柄（共享会导致协议错乱）。

    配置来自 DB_CONFIG['pool']（YAML database.pool 段，base 文件兜底默认值）。
    """
    global _pool, _pool_pid
    if _pool is not None and _pool_pid == os.getpid():
        return _pool
    with _pool_lock:
        # double-checked locking，避免并发重复建池
        if _pool is None or _pool_pid != os.getpid():
            pool_cfg = DB_CONFIG.get('pool') or {}
            mincached = pool_cfg.get('mincached', 2)
            maxcached = pool_cfg.get('maxcached', 20)
            maxconnections = pool_cfg.get('maxconnections', 0)
            _pool = PooledDB(
                creator=pymysql,
                mincached=mincached,        # 启动时预热连接数
                maxcached=maxcached,        # 空闲池上限；超出归还时真关闭
                maxconnections=maxconnections,  # 0=无硬上限，复用优先，避免池满死锁
                # blocking 仅在 maxconnections>0 时生效（池满时阻塞等待复用 vs 抛错）；
                # 默认无硬上限，此处保留语义以备将来按需开启
                blocking=True,
                maxusage=0,                  # 连接不限复用次数
                reset=True,                  # 归还时自动 ROLLBACK（契合 autocommit=False）
                ping=1,                      # 借出时 ping 检查连接活性
                # 以下透传给 pymysql.connect（与改造前参数完全一致，仅新增 connect_timeout）
                host=DB_CONFIG['host'],
                port=DB_CONFIG['port'],
                user=DB_CONFIG['user'],
                password=DB_CONFIG['password'],
                database=DB_CONFIG['database'],
                charset=DB_CONFIG['charset'],
                cursorclass=DictCursor,
                autocommit=False,
                connect_timeout=DB_POOL_CONNECT_TIMEOUT,
                # 故意不设 read_timeout：保持现状的无限等待（彻底零破坏），
                # 避免误杀 cleanup 类批量 DELETE/UPDATE（已通过补索引缓解，
                # 但批量 DELETE 仍可能慢，维持不设以保留原行为）
            )
            _pool_pid = os.getpid()
            logger.info(
                f"[DBPool] 连接池已创建 pid={_pool_pid} "
                f"mincached={mincached} maxcached={maxcached} "
                f"maxconnections={maxconnections}"
            )
    return _pool


@contextmanager
def get_db_connection():
    """
    Get database connection context manager
    Usage:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_tools")
            results = cursor.fetchall()

    实现说明：从连接池借用连接。with 块结束时 finally 里的 conn.close()
    在池化语义下是「归还到池」而非「真关闭 TCP」，由 DBUtils 接管复用。
    """
    connection = None
    try:
        connection = _get_pool().connection()
        yield connection
    except Exception as e:
        logger.error(f"Database connection error: {e}")
        raise
    finally:
        if connection:
            connection.close()


def execute_query(sql, params=None, fetch_one=False, fetch_all=False):
    """
    Execute a SELECT query and return results
    
    Args:
        sql: SQL query string
        params: Query parameters (tuple or dict)
        fetch_one: Return single row
        fetch_all: Return all rows
    
    Returns:
        Query results or None
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        
        if fetch_one:
            return cursor.fetchone()
        elif fetch_all:
            return cursor.fetchall()
        return None


def execute_update(sql, params=None):
    """
    Execute an INSERT, UPDATE, or DELETE query
    
    Args:
        sql: SQL query string
        params: Query parameters (tuple or dict)
    
    Returns:
        Number of affected rows
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        affected_rows = cursor.execute(sql, params or ())
        conn.commit()
        return affected_rows


def execute_insert(sql, params=None):
    """
    Execute an INSERT query and return the last inserted ID

    Args:
        sql: SQL query string
        params: Query parameters (tuple or dict)

    Returns:
        Last inserted ID
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        conn.commit()
        return cursor.lastrowid


@contextmanager
def transaction():
    """
    事务上下文管理器，在同一连接内执行多个操作，自动处理 commit/rollback

    用法:
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(sql1, params1)
            cursor.execute(sql2, params2)
            # 自动 commit，异常时自动 rollback

    实现说明：借出连接后立即 conn.begin()。begin() 会告知池层（DBUtils
    SteadyDB）"进入事务"，从而禁用其透明重连重试机制——事务中途连接出错
    时错误直接抛出（走下方 rollback），而不是在新连接上静默重试失败语句，
    否则多语句事务会只提交后半段、原子性被悄悄破坏。begin() 在
    autocommit=False 下不改变提交时机（数据仍只在 conn.commit() 时落库），
    也不影响非事务连接（它们永不调用 begin，透明重试/自愈行为不变）。

    Returns:
        数据库连接对象
    """
    with get_db_connection() as conn:
        conn.begin()  # 进入显式事务：禁用 SteadyDB 透明重试，保住原子性
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def execute_insert_in_transaction(conn, sql, params=None):
    """
    在指定事务连接内执行 INSERT，返回 lastrowid

    Args:
        conn: transaction() 上下文中的连接对象
        sql: SQL query string
        params: Query parameters (tuple or dict)

    Returns:
        Last inserted ID
    """
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    return cursor.lastrowid


def execute_update_in_transaction(conn, sql, params=None):
    """
    在指定事务连接内执行 UPDATE/DELETE，返回 affected rows

    Args:
        conn: transaction() 上下文中的连接对象
        sql: SQL query string
        params: Query parameters (tuple or dict)

    Returns:
        Number of affected rows
    """
    cursor = conn.cursor()
    return cursor.execute(sql, params or ())


def execute_query_in_transaction(conn, sql, params=None, fetch_one=False):
    """
    在事务连接内执行 SELECT（如 FOR UPDATE 行锁）。

    ⚠️ 仅供事务型原子操作内部调用，禁止用于在持有 conn 时执行会阻塞的操作。
    与 execute_insert_in_transaction / execute_update_in_transaction 配套，
    三者构成「事务内只做 DB 操作」的完整工具集。事务必须保持毫秒级短事务，
    严禁在持有 conn 期间夹带 HTTP / 文件 IO / TTS / time.sleep 等慢操作，
    否则行锁长期持有会阻塞并发更新。

    Args:
        conn: transaction() 上下文中的连接对象
        sql: SQL query string（可含 FOR UPDATE）
        params: Query parameters (tuple or dict)
        fetch_one: True 返回单行，False 返回多行列表

    Returns:
        单行 dict（fetch_one=True）或 行列表（fetch_one=False）
    """
    cursor = conn.cursor()
    cursor.execute(sql, params or ())
    return cursor.fetchone() if fetch_one else cursor.fetchall()
