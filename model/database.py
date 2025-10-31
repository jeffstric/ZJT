"""
Database connection configuration
"""
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager
import os
import yaml
import logging

logger = logging.getLogger(__name__)

# Load database configuration from config file
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
config_file = os.path.join(APP_DIR, 'config.yml')

# Default database configuration
DB_CONFIG = {
    'host': '192.168.10.212',
    'port': 3306,
    'user': 'voice_replace_app',
    'password': 'hq5cp53iL9pjjUQQb5Z3qF7C',
    'database': 'voice_replace',
    'charset': 'utf8mb4'
}

# Try to load from config file if exists
if os.path.exists(config_file):
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            if config and 'database' in config:
                DB_CONFIG.update(config['database'])
    except Exception as e:
        logger.warning(f"Failed to load database config from file: {e}")

# Override with environment variables if set
DB_CONFIG['host'] = os.environ.get('DB_HOST', DB_CONFIG['host'])
DB_CONFIG['port'] = int(os.environ.get('DB_PORT', DB_CONFIG['port']))
DB_CONFIG['user'] = os.environ.get('DB_USER', DB_CONFIG['user'])
DB_CONFIG['password'] = os.environ.get('DB_PASSWORD', DB_CONFIG['password'])
DB_CONFIG['database'] = os.environ.get('DB_NAME', DB_CONFIG['database'])


@contextmanager
def get_db_connection():
    """
    Get database connection context manager
    Usage:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM ai_tools")
            results = cursor.fetchall()
    """
    connection = None
    try:
        connection = pymysql.connect(
            host=DB_CONFIG['host'],
            port=DB_CONFIG['port'],
            user=DB_CONFIG['user'],
            password=DB_CONFIG['password'],
            database=DB_CONFIG['database'],
            charset=DB_CONFIG['charset'],
            cursorclass=DictCursor,
            autocommit=False
        )
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
