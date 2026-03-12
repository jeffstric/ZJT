"""
测试数据库配置模块 - 支持独立 config_unit.yml 配置文件
提供测试数据库连接配置，支持从环境变量读取测试库配置
"""
import os
import sys
import yaml
import logging

logger = logging.getLogger(__name__)

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from config.config_util import get_config_path


def get_unit_test_config_path():
    """
    获取单元测试配置文件路径
    
    优先级：
    1. 环境变量 UNIT_TEST_CONFIG
    2. 默认 config_unit.yml
    
    Returns:
        str: 配置文件路径
    """
    return os.environ.get('UNIT_TEST_CONFIG', 'config_unit.yml')


def get_test_db_config():
    """
    获取测试数据库配置
    
    配置优先级：
    1. 环境变量 (TEST_DB_HOST, TEST_DB_PORT, TEST_DB_USER, TEST_DB_PASSWORD, TEST_DB_NAME)
    2. config_unit.yml 中的 database 配置节
    3. config.yml 中的 test_database 配置节
    4. config.yml 中的 database 配置节
    5. 默认值
    
    安全机制：
    - 数据库名必须以 _test 或 _unittest 结尾
    
    Returns:
        dict: 数据库配置字典
    """
    db_config = {}
    
    # 1. 尝试加载 config_unit.yml（优先）
    unit_config_file = os.path.join(APP_DIR, get_unit_test_config_path())
    if os.path.exists(unit_config_file):
        try:
            with open(unit_config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                if config:
                    # 优先使用 test_database，其次 database
                    if 'test_database' in config:
                        db_config = config['test_database'].copy()
                        logger.info(f"使用 {get_unit_test_config_path()} 中的 test_database 配置")
                    elif 'database' in config:
                        db_config = config['database'].copy()
                        logger.info(f"使用 {get_unit_test_config_path()} 中的 database 配置")
        except Exception as e:
            logger.error(f"加载测试配置文件失败: {e}")
    
    # 2. 如果没有 config_unit.yml，回退到 config.yml
    if not db_config:
        config_file = os.path.join(APP_DIR, get_config_path())
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                    if config:
                        if 'test_database' in config:
                            db_config = config['test_database'].copy()
                            logger.info("使用 config.yml 中的 test_database 配置")
                        elif 'database' in config:
                            db_config = config['database'].copy()
                            logger.info("使用 config.yml 中的 database 配置")
            except Exception as e:
                logger.warning(f"Failed to load config file: {e}")
    
    # 3. 环境变量覆盖（优先级最高）
    db_config['host'] = os.environ.get('TEST_DB_HOST', db_config.get('host', 'localhost'))
    db_config['port'] = int(os.environ.get('TEST_DB_PORT', db_config.get('port', 3306)))
    db_config['user'] = os.environ.get('TEST_DB_USER', db_config.get('user', 'root'))
    db_config['password'] = os.environ.get('TEST_DB_PASSWORD', db_config.get('password', ''))
    db_config['database'] = os.environ.get('TEST_DB_NAME', db_config.get('database', 'comfyui_test'))
    db_config['charset'] = db_config.get('charset', 'utf8mb4')
    
    # 4. 安全校验：数据库名必须以 _test 或 _unittest 结尾
    db_name = db_config['database']
    if not (db_name.endswith('_test') or db_name.endswith('_unittest')):
        raise ValueError(
            f"测试数据库名称 '{db_name}' 必须以 '_test' 或 '_unittest' 结尾，"
            f"以防止误操作生产数据库"
        )
    
    logger.info(f"测试数据库配置: host={db_config['host']}, database={db_config['database']}")
    return db_config


# 全局配置常量
TEST_DB_CONFIG = get_test_db_config()


def get_unit_test_setting(key, default=None):
    """
    获取单元测试专用配置项
    
    Args:
        key: 配置键名（如 'unit_test.mock_external_apis'）
        default: 默认值
        
    Returns:
        配置值或默认值
    """
    config_file = os.path.join(APP_DIR, get_unit_test_config_path())
    
    if not os.path.exists(config_file):
        return default
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            
        # 支持嵌套键（如 'unit_test.mock_external_apis'）
        keys = key.split('.')
        value = config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value
    except Exception:
        return default


# 缓存单元测试配置
_unit_config_cache = None


def get_unit_config():
    """
    获取完整的单元测试配置（带缓存）
    
    Returns:
        dict: 完整的配置字典
    """
    global _unit_config_cache
    
    if _unit_config_cache is not None:
        return _unit_config_cache
    
    config_file = os.path.join(APP_DIR, get_unit_test_config_path())
    
    if not os.path.exists(config_file):
        _unit_config_cache = {}
        return _unit_config_cache
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            _unit_config_cache = yaml.safe_load(f) or {}
    except Exception as e:
        logger.error(f"加载单元测试配置文件失败: {e}")
        _unit_config_cache = {}
    
    return _unit_config_cache


def get_unit_config_value(*keys, default=None):
    """
    获取单元测试配置中的指定值（支持多层级键）
    
    用于替代驱动测试中的 mock get_dynamic_config_value
    
    Args:
        *keys: 配置键路径，如 'server', 'is_local' 表示 config['server']['is_local']
        default: 键不存在时的默认值
        
    Returns:
        配置值或默认值
        
    Example:
        >>> get_unit_config_value('server', 'is_local', default=False)
        >>> get_unit_config_value('timeout', 'request_timeout', default=30)
    """
    config = get_unit_config()
    
    result = config
    for key in keys:
        if isinstance(result, dict):
            result = result.get(key)
        else:
            return default
        if result is None:
            return default
    
    return result if result is not None else default


def get_test_db_connection():
    """
    获取测试数据库连接上下文管理器
    
    Usage:
        from tests.db_test_config import get_test_db_connection
        with get_test_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_tools")
            results = cursor.fetchall()
    """
    import pymysql
    from pymysql.cursors import DictCursor
    from contextlib import contextmanager
    
    @contextmanager
    def _connection():
        connection = None
        try:
            connection = pymysql.connect(
                host=TEST_DB_CONFIG['host'],
                port=TEST_DB_CONFIG['port'],
                user=TEST_DB_CONFIG['user'],
                password=TEST_DB_CONFIG['password'],
                database=TEST_DB_CONFIG['database'],
                charset=TEST_DB_CONFIG['charset'],
                cursorclass=DictCursor,
                autocommit=False
            )
            yield connection
        except Exception as e:
            logger.error(f"Test database connection error: {e}")
            raise
        finally:
            if connection:
                connection.close()
    
    return _connection()
