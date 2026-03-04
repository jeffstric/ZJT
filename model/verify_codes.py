"""
VerifyCodes Model - Database operations for verify_codes table
对应Go的models/verify_codes.go
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class VerifyCode:
    """VerifyCode model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.phone = kwargs.get('phone')
        self.code = kwargs.get('code')
        self.code_type = kwargs.get('type') or kwargs.get('code_type', 'register')
        self.expire_time = kwargs.get('expire_time')
        self.used = kwargs.get('used', False)
        self.created_at = kwargs.get('created_at')
    
    def is_expired(self) -> bool:
        """检查验证码是否过期"""
        if self.expire_time:
            return datetime.now() > self.expire_time
        return True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'phone': self.phone,
            'code': self.code,
            'expire_time': self.expire_time.isoformat() if self.expire_time else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class VerifyCodesModel:
    """VerifyCodes database operations"""
    
    @staticmethod
    def create(phone: str, code: str, code_type: str = "register", expire_time: Optional[datetime] = None) -> int:
        """创建验证码记录"""
        if expire_time is None:
            expire_time = datetime.now() + timedelta(minutes=5)
        sql = """
            INSERT INTO verify_codes (phone, code, type, expire_time)
            VALUES (%s, %s, %s, %s)
        """
        try:
            code_id = execute_insert(sql, (phone, code, code_type, expire_time))
            logger.info(f"Created verify code for phone: {phone}, type: {code_type}")
            return code_id
        except Exception as e:
            logger.error(f"Failed to create verify code: {e}")
            raise
    
    @staticmethod
    def get_latest_by_phone(phone: str) -> Optional[VerifyCode]:
        """获取手机号最新的验证码"""
        sql = """
            SELECT * FROM verify_codes 
            WHERE phone = %s 
            ORDER BY created_at DESC 
            LIMIT 1
        """
        try:
            result = execute_query(sql, (phone,), fetch_one=True)
            if result:
                return VerifyCode(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get verify code for phone {phone}: {e}")
            raise
    
    @staticmethod
    def verify(phone: str, code: str, code_type: str = "register") -> bool:
        """验证验证码是否正确、未过期且未使用"""
        sql = """
            SELECT * FROM verify_codes 
            WHERE phone = %s AND code = %s AND type = %s 
            AND expire_time > NOW() AND (used = 0 OR used IS NULL)
            ORDER BY created_at DESC 
            LIMIT 1
        """
        try:
            result = execute_query(sql, (phone, code, code_type), fetch_one=True)
            return result is not None
        except Exception as e:
            logger.error(f"Failed to verify code for phone {phone}: {e}")
            raise
    
    @staticmethod
    def mark_used(phone: str, code: str, code_type: str = "register") -> int:
        """标记验证码为已使用"""
        sql = "UPDATE verify_codes SET used = 1 WHERE phone = %s AND code = %s AND type = %s"
        try:
            return execute_update(sql, (phone, code, code_type))
        except Exception as e:
            logger.error(f"Failed to mark verify code as used: {e}")
            raise
    
    @staticmethod
    def delete_by_phone(phone: str) -> int:
        """删除手机号的所有验证码"""
        sql = "DELETE FROM verify_codes WHERE phone = %s"
        try:
            return execute_update(sql, (phone,))
        except Exception as e:
            logger.error(f"Failed to delete verify codes for phone {phone}: {e}")
            raise
    
    @staticmethod
    def delete_expired() -> int:
        """删除所有过期的验证码"""
        sql = "DELETE FROM verify_codes WHERE expire_time < NOW()"
        try:
            return execute_update(sql)
        except Exception as e:
            logger.error(f"Failed to delete expired verify codes: {e}")
            raise
