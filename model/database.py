"""
Database connection configuration
"""
import pymysql
from pymysql.cursors import DictCursor
from contextlib import contextmanager
import os
import logging

logger = logging.getLogger(__name__)

# Load database configuration using unified config utility
from config.config_util import get_config_value

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
