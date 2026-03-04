"""
TokenLog Model - Database operations for token_log table
对应Go的models/token_log.go
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class TokenLog:
    """TokenLog model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.token_type = kwargs.get('token_type')
        self.amount = kwargs.get('amount')
        self.behavior = kwargs.get('behavior')
        self.note = kwargs.get('note')
        self.transaction_id = kwargs.get('transaction_id')
        self.input_token = kwargs.get('input_token')
        self.output_token = kwargs.get('output_token')
        self.cache_read = kwargs.get('cache_read')
        self.cache_creation = kwargs.get('cache_creation')
        self.vendor_id = kwargs.get('vendor_id')
        self.model_id = kwargs.get('model_id')
        self.status = kwargs.get('status', 0)
        self.created_at = kwargs.get('created_at')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'token_type': self.token_type,
            'amount': self.amount,
            'behavior': self.behavior,
            'note': self.note,
            'transaction_id': self.transaction_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class TokenLogModel:
    """TokenLog database operations"""
    
    @staticmethod
    def create(
        user_id: int,
        input_token: Optional[int] = None,
        output_token: Optional[int] = None,
        cache_read: Optional[int] = None,
        cache_creation: Optional[int] = None,
        vendor_id: Optional[int] = None,
        model_id: Optional[int] = None,
        note: Optional[str] = None,
        status: int = 0
    ) -> int:
        """
        创建token日志
        对应Go的models.CreateTokenLog
        """
        sql = """
            INSERT INTO token_log (input_token, output_token, cache_read, cache_creation, 
                                   vendor_id, model_id, user_id, note, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        try:
            log_id = execute_insert(sql, (
                input_token, output_token, cache_read, cache_creation,
                vendor_id, model_id, user_id, note, status
            ))
            logger.info(f"Created token log with ID: {log_id}")
            return log_id
        except Exception as e:
            logger.error(f"Failed to create token log: {e}")
            raise
    
    @staticmethod
    def get_by_user_id(
        user_id: int,
        token_type: Optional[str] = None,
        behavior: Optional[str] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[TokenLog]:
        """获取用户的token日志"""
        sql = "SELECT * FROM token_log WHERE user_id = %s"
        params = [user_id]
        
        if token_type:
            sql += " AND token_type = %s"
            params.append(token_type)
        
        if behavior:
            sql += " AND behavior = %s"
            params.append(behavior)
        
        sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
        params.extend([limit, offset])
        
        try:
            results = execute_query(sql, tuple(params), fetch_all=True)
            return [TokenLog(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get token logs for user {user_id}: {e}")
            raise
    
    @staticmethod
    def get_count(
        user_id: int,
        token_type: Optional[str] = None,
        behavior: Optional[str] = None
    ) -> int:
        """获取用户的token日志数量"""
        sql = "SELECT COUNT(*) as count FROM token_log WHERE user_id = %s"
        params = [user_id]
        
        if token_type:
            sql += " AND token_type = %s"
            params.append(token_type)
        
        if behavior:
            sql += " AND behavior = %s"
            params.append(behavior)
        
        try:
            result = execute_query(sql, tuple(params), fetch_one=True)
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to get token logs count for user {user_id}: {e}")
            raise
    
    @staticmethod
    def check_transaction_exists(transaction_id: str) -> bool:
        """检查transaction_id是否已存在（幂等性检查）"""
        sql = "SELECT COUNT(*) as count FROM token_log WHERE transaction_id = %s"
        try:
            result = execute_query(sql, (transaction_id,), fetch_one=True)
            return result['count'] > 0 if result else False
        except Exception as e:
            logger.error(f"Failed to check transaction exists: {e}")
            raise
    
    @staticmethod
    def get_unprocessed(limit: int = 100) -> List[TokenLog]:
        """获取未处理的token日志"""
        sql = """
            SELECT * FROM token_log 
            WHERE status = 0 OR status IS NULL
            ORDER BY created_at ASC 
            LIMIT %s
        """
        try:
            results = execute_query(sql, (limit,), fetch_all=True)
            return [TokenLog(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get unprocessed token logs: {e}")
            raise
    
    @staticmethod
    def update_status(log_id: int, status: int) -> int:
        """更新token日志状态"""
        sql = "UPDATE token_log SET status = %s WHERE id = %s"
        try:
            return execute_update(sql, (status, log_id))
        except Exception as e:
            logger.error(f"Failed to update token log status: {e}")
            raise
