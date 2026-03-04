"""
ComputingPowerLog Model - Database operations for computing_power_log table
对应Go的models/computing_power_log.go
"""
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class ComputingPowerLog:
    """ComputingPowerLog model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.behavior = kwargs.get('behavior')
        self.message = kwargs.get('message')
        self.note = kwargs.get('note')
        self.computing_power = kwargs.get('computing_power')
        self.from_value = kwargs.get('from')
        self.to_value = kwargs.get('to')
        self.transaction_id = kwargs.get('transaction_id')
        self.created_at = kwargs.get('created_at')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'behavior': self.behavior,
            'message': self.message,
            'note': self.note,
            'computing_power': self.computing_power,
            'from': self.from_value,
            'to': self.to_value,
            'transaction_id': self.transaction_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class ComputingPowerLogModel:
    """ComputingPowerLog database operations"""
    
    @staticmethod
    def create(
        user_id: int,
        behavior: str,
        computing_power: int,
        from_value: int,
        to_value: int,
        message: Optional[str] = None,
        note: Optional[str] = None,
        transaction_id: Optional[str] = None
    ) -> int:
        """创建算力日志记录"""
        sql = """
            INSERT INTO computing_power_log 
            (user_id, behavior, computing_power, `from`, `to`, message, note, transaction_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            log_id = execute_insert(sql, (user_id, behavior, computing_power, from_value, to_value, message, note, transaction_id))
            logger.info(f"Created computing power log with ID: {log_id}")
            return log_id
        except Exception as e:
            logger.error(f"Failed to create computing power log: {e}")
            raise
    
    @staticmethod
    def get_by_user_id(user_id: int, limit: int = 20, offset: int = 0) -> List[ComputingPowerLog]:
        """根据用户ID获取算力日志"""
        sql = """
            SELECT * FROM computing_power_log 
            WHERE user_id = %s 
            ORDER BY created_at DESC 
            LIMIT %s OFFSET %s
        """
        try:
            results = execute_query(sql, (user_id, limit, offset), fetch_all=True)
            return [ComputingPowerLog(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get computing power logs for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_by_behavior(behavior: str, limit: int = 20, offset: int = 0) -> List[ComputingPowerLog]:
        """根据行为类型获取算力日志"""
        sql = """
            SELECT * FROM computing_power_log 
            WHERE behavior = %s 
            ORDER BY created_at DESC 
            LIMIT %s OFFSET %s
        """
        try:
            results = execute_query(sql, (behavior, limit, offset), fetch_all=True)
            return [ComputingPowerLog(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get computing power logs by behavior {behavior}: {e}")
            raise
    
    @staticmethod
    def get_all(
        user_id: Optional[int] = None,
        behavior: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[ComputingPowerLog]:
        """获取算力日志（支持可选的userID和behavior筛选）"""
        sql = "SELECT * FROM computing_power_log WHERE 1=1"
        params = []
        
        if user_id is not None:
            sql += " AND user_id = %s"
            params.append(user_id)
        
        if behavior:
            sql += " AND behavior = %s"
            params.append(behavior)
        
        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        try:
            results = execute_query(sql, tuple(params), fetch_all=True)
            return [ComputingPowerLog(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get computing power logs: {e}")
            raise
    
    @staticmethod
    def get_count(user_id: Optional[int] = None, behavior: Optional[str] = None) -> int:
        """获取算力日志总数"""
        sql = "SELECT COUNT(*) as count FROM computing_power_log WHERE 1=1"
        params = []
        
        if user_id is not None:
            sql += " AND user_id = %s"
            params.append(user_id)
        
        if behavior:
            sql += " AND behavior = %s"
            params.append(behavior)
        
        try:
            result = execute_query(sql, tuple(params), fetch_one=True)
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get computing power logs count: {e}")
            raise
    
    @staticmethod
    def get_invitation_reward_stats(user_id: int) -> Dict[str, int]:
        """获取用户邀请奖励算力统计"""
        sql = """
            SELECT 
                COUNT(*) as count,
                COALESCE(SUM(computing_power), 0) as total_power
            FROM computing_power_log 
            WHERE user_id = %s 
            AND behavior = 'increase' 
            AND note LIKE '%%邀请奖励算力%%'
        """
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return {
                'count': int(result['count']) if result else 0,
                'total_power': int(result['total_power']) if result else 0
            }
        except Exception as e:
            logger.error(f"Failed to get invitation reward stats for user {user_id}: {e}")
            raise
    
    @staticmethod
    def check_transaction_exists(transaction_id: str) -> bool:
        """检查transaction_id是否已存在（幂等性检查）"""
        sql = "SELECT COUNT(*) as count FROM computing_power_log WHERE transaction_id = %s"
        try:
            result = execute_query(sql, (transaction_id,), fetch_one=True)
            return result['count'] > 0 if result else False
        except Exception as e:
            logger.error(f"Failed to check transaction exists: {e}")
            raise
