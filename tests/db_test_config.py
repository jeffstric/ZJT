"""
测试数据库配置模块
提供测试数据库连接配置，支持从环境变量读取测试库配置
"""
import os
import sys
import yaml
import logging

logger = logging.getLogger(__name__)

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)

from config_util import get_config_path


def get_test_db_config():
    """
    获取测试数据库配置
    优先级：环境变量 > test_database 配置 > database 配置（自动添加 _test 后缀）
    
    Returns:
        dict: 数据库配置字典
    """
    config_file = os.path.join(APP_DIR, get_config_path())
    db_config = {}
    
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
                        logger.info("使用 config.yml 中的 database 配置（将自动添加 _test 后缀）")
        except Exception as e:
            logger.warning(f"Failed to load config file: {e}")
    
    db_config['host'] = os.environ.get('TEST_DB_HOST', db_config.get('host', 'localhost'))
    db_config['port'] = int(os.environ.get('TEST_DB_PORT', db_config.get('port', 3306)))
    db_config['user'] = os.environ.get('TEST_DB_USER', db_config.get('user', 'root'))
    db_config['password'] = os.environ.get('TEST_DB_PASSWORD', db_config.get('password', ''))
    
    default_db_name = db_config.get('database', 'comfyui')
    test_db_name = os.environ.get('TEST_DB_NAME', default_db_name)
  
    db_config['database'] = test_db_name
    
    if 'charset' not in db_config:
        db_config['charset'] = 'utf8mb4'
    
    return db_config


TEST_DB_CONFIG = get_test_db_config()


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
