"""
LoginLog Model - Database operations for login_logs table
对应Go的models/login_logs.go
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class LoginLog:
    """LoginLog model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.ip_address = kwargs.get('ip_address')
        self.user_agent = kwargs.get('user_agent')
        self.status = kwargs.get('status', 1)
        self.created_at = kwargs.get('created_at')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class LoginLogModel:
    """LoginLog database operations"""
    
    @staticmethod
    def create(
        user_id: int,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        status: int = 1
    ) -> int:
        """创建登录日志"""
        sql = """
            INSERT INTO login_logs (user_id, ip_address, user_agent, status)
            VALUES (%s, %s, %s, %s)
        """
        try:
            log_id = execute_insert(sql, (user_id, ip_address, user_agent, status))
            logger.info(f"Created login log with ID: {log_id}")
            return log_id
        except Exception as e:
            logger.error(f"Failed to create login log: {e}")
            raise
    
    @staticmethod
    def get_by_user_id(user_id: int, limit: int = 20, offset: int = 0) -> List[LoginLog]:
        """获取用户的登录日志"""
        sql = """
            SELECT * FROM login_logs 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s OFFSET %s
        """
        try:
            results = execute_query(sql, (user_id, limit, offset), fetch_all=True)
            return [LoginLog(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get login logs for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_last_login(user_id: int) -> Optional[LoginLog]:
        """获取用户最后一次成功登录记录"""
        sql = """
            SELECT * FROM login_logs 
            WHERE user_id = %s AND status = 1
            ORDER BY created_at DESC 
            LIMIT 1
        """
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if result:
                return LoginLog(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get last login for user {user_id}: {e}")
            raise
