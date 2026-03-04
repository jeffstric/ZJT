"""
UncalculatedToken Model - 未计算token表
对应Go的models/uncalculated_token.go
"""
from typing import Optional
from datetime import datetime
from model.database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class UncalculatedToken:
    """未计算token实体"""
    
    def __init__(
        self,
        id: int = 0,
        user_id: int = 0,
        uncalculated_input_token: Optional[int] = None,
        uncalculated_output_token: Optional[int] = None,
        uncalculated_cache_read: Optional[int] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.id = id
        self.user_id = user_id
        self.uncalculated_input_token = uncalculated_input_token
        self.uncalculated_output_token = uncalculated_output_token
        self.uncalculated_cache_read = uncalculated_cache_read
        self.created_at = created_at
        self.updated_at = updated_at


class UncalculatedTokenModel:
    """未计算token数据库操作"""
    
    @staticmethod
    def create(
        user_id: int,
        input_token: Optional[int] = None,
        output_token: Optional[int] = None,
        cache_read: Optional[int] = None
    ) -> int:
        """创建未计算token记录"""
        sql = """INSERT INTO uncalculated_token 
               (user_id, uncalculated_input_token, uncalculated_output_token, uncalculated_cache_read) 
               VALUES (%s, %s, %s, %s)"""
        try:
            return execute_insert(sql, (user_id, input_token, output_token, cache_read))
        except Exception as e:
            logger.error(f"Failed to create uncalculated token: {e}")
            raise
    
    @staticmethod
    def get_by_user_id(user_id: int) -> Optional[UncalculatedToken]:
        """根据用户ID获取未计算token记录"""
        sql = """SELECT id, user_id, uncalculated_input_token, uncalculated_output_token, 
               uncalculated_cache_read, created_at, updated_at 
               FROM uncalculated_token WHERE user_id = %s"""
        try:
            row = execute_query(sql, (user_id,), fetch_one=True)
            if not row:
                return None
            return UncalculatedToken(
                id=row['id'],
                user_id=row['user_id'],
                uncalculated_input_token=row['uncalculated_input_token'],
                uncalculated_output_token=row['uncalculated_output_token'],
                uncalculated_cache_read=row['uncalculated_cache_read'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
        except Exception as e:
            logger.error(f"Failed to get uncalculated token for user {user_id}: {e}")
            raise
    
    @staticmethod
    def update(
        user_id: int,
        input_token: Optional[int] = None,
        output_token: Optional[int] = None,
        cache_read: Optional[int] = None
    ) -> bool:
        """更新用户的未计算token"""
        sql = """UPDATE uncalculated_token 
               SET uncalculated_input_token = %s, uncalculated_output_token = %s, 
                   uncalculated_cache_read = %s, updated_at = CURRENT_TIMESTAMP 
               WHERE user_id = %s"""
        try:
            rows = execute_update(sql, (input_token, output_token, cache_read, user_id))
            return rows > 0
        except Exception as e:
            logger.error(f"Failed to update uncalculated token for user {user_id}: {e}")
            raise
    
    @staticmethod
    def delete(user_id: int) -> bool:
        """删除用户的未计算token记录"""
        sql = "DELETE FROM uncalculated_token WHERE user_id = %s"
        try:
            rows = execute_update(sql, (user_id,))
            return rows > 0
        except Exception as e:
            logger.error(f"Failed to delete uncalculated token for user {user_id}: {e}")
            raise
