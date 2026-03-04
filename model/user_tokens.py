"""
UserTokens Model - Database operations for user_tokens table
对应Go的models/user_tokens.go
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class UserToken:
    """UserToken model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.token = kwargs.get('token')
        self.device_uuid = kwargs.get('device_uuid')
        self.expire_time = kwargs.get('expire_time')
        self.created_at = kwargs.get('created_at')
    
    def is_expired(self) -> bool:
        """检查token是否过期"""
        if self.expire_time:
            return datetime.now() > self.expire_time
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'token': self.token,
            'device_uuid': self.device_uuid,
            'expire_time': self.expire_time.isoformat() if self.expire_time else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class UserTokensModel:
    """UserTokens database operations"""
    
    @staticmethod
    def create(user_id: int, token: str, expire_time: datetime, device_uuid: Optional[str] = None) -> int:
        """创建用户token"""
        sql = """
            INSERT INTO user_tokens (user_id, token, expire_time, device_uuid)
            VALUES (%s, %s, %s, %s)
        """
        try:
            token_id = execute_insert(sql, (user_id, token, expire_time, device_uuid))
            logger.info(f"Created user token with ID: {token_id}")
            return token_id
        except Exception as e:
            logger.error(f"Failed to create user token: {e}")
            raise
    
    @staticmethod
    def get_by_token(token: str) -> Optional[UserToken]:
        """根据token获取记录"""
        sql = "SELECT * FROM user_tokens WHERE token = %s"
        try:
            result = execute_query(sql, (token,), fetch_one=True)
            if result:
                return UserToken(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get user token: {e}")
            raise
    
    @staticmethod
    def get_valid_token(token: str) -> Optional[UserToken]:
        """获取有效的token（未过期）"""
        sql = "SELECT * FROM user_tokens WHERE token = %s AND expire_time > NOW()"
        try:
            result = execute_query(sql, (token,), fetch_one=True)
            if result:
                return UserToken(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get valid token: {e}")
            raise
    
    @staticmethod
    def get_user_id_by_token(token: str) -> Optional[int]:
        """根据token获取用户ID（验证token有效性）"""
        sql = "SELECT user_id FROM user_tokens WHERE token = %s AND expire_time > NOW()"
        try:
            result = execute_query(sql, (token,), fetch_one=True)
            return result['user_id'] if result else None
        except Exception as e:
            logger.error(f"Failed to get user_id by token: {e}")
            raise
    
    @staticmethod
    def delete_by_token(token: str) -> int:
        """删除token"""
        sql = "DELETE FROM user_tokens WHERE token = %s"
        try:
            return execute_update(sql, (token,))
        except Exception as e:
            logger.error(f"Failed to delete token: {e}")
            raise
    
    @staticmethod
    def delete_by_user_id(user_id: int) -> int:
        """删除用户的所有token"""
        sql = "DELETE FROM user_tokens WHERE user_id = %s"
        try:
            return execute_update(sql, (user_id,))
        except Exception as e:
            logger.error(f"Failed to delete tokens for user {user_id}: {e}")
            raise
    
    @staticmethod
    def delete_expired() -> int:
        """删除所有过期的token"""
        sql = "DELETE FROM user_tokens WHERE expire_time < NOW()"
        try:
            return execute_update(sql)
        except Exception as e:
            logger.error(f"Failed to delete expired tokens: {e}")
            raise
    
    @staticmethod
    def get_token_by_user_id(user_id: int) -> Optional[str]:
        """
        根据用户ID获取有效的token
        对应Go的models.GetTokenByUserID
        """
        sql = "SELECT token FROM user_tokens WHERE user_id = %s AND expire_time > NOW() ORDER BY created_at DESC LIMIT 1"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return result['token'] if result else None
        except Exception as e:
            logger.error(f"Failed to get token by user_id {user_id}: {e}")
            raise
