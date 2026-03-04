"""
ComputingPower Model - Database operations for computing_power table
对应Go的models/computing_power.go
"""
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
from .computing_power_log import ComputingPowerLogModel
import logging

logger = logging.getLogger(__name__)


class ComputingPower:
    """ComputingPower model class"""
    
    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.computing_power = kwargs.get('computing_power', 0)
        self.expiration_time = kwargs.get('expiration_time')
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'computing_power': self.computing_power,
            'expiration_time': self.expiration_time.isoformat() if self.expiration_time else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class ComputingPowerModel:
    """ComputingPower database operations"""
    
    @staticmethod
    def get_by_user_id(user_id: int) -> Optional[ComputingPower]:
        """根据用户ID获取算力信息"""
        sql = "SELECT * FROM computing_power WHERE user_id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            if result:
                return ComputingPower(**result)
            return None
        except Exception as e:
            logger.error(f"Failed to get computing power for user {user_id}: {e}")
            raise
    
    @staticmethod
    def create(user_id: int, computing_power: int = 0, expiration_time: Optional[datetime] = None) -> int:
        """创建新的算力记录（如果已存在会抛出异常）"""
        sql = """
            INSERT INTO computing_power (user_id, computing_power, expiration_time)
            VALUES (%s, %s, %s)
        """
        try:
            record_id = execute_insert(sql, (user_id, computing_power, expiration_time))
            logger.info(f"Created computing power record with ID: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create computing power record: {e}")
            raise

    @staticmethod
    def create_or_update(user_id: int, computing_power: int = 0, expiration_time: Optional[datetime] = None) -> int:
        """创建或更新算力记录（使用 INSERT ON DUPLICATE KEY UPDATE 避免重复插入）"""
        sql = """
            INSERT INTO computing_power (user_id, computing_power, expiration_time)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                computing_power = VALUES(computing_power),
                expiration_time = VALUES(expiration_time),
                updated_at = NOW()
        """
        try:
            record_id = execute_insert(sql, (user_id, computing_power, expiration_time))
            logger.info(f"Created or updated computing power record for user {user_id}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create or update computing power record: {e}")
            raise
    
    @staticmethod
    def update(user_id: int, computing_power: int) -> int:
        """更新用户算力"""
        sql = "UPDATE computing_power SET computing_power = %s, updated_at = NOW() WHERE user_id = %s"
        try:
            return execute_update(sql, (computing_power, user_id))
        except Exception as e:
            logger.error(f"Failed to update computing power for user {user_id}: {e}")
            raise
    
    @staticmethod
    def update_with_expiration(user_id: int, computing_power: int, expiration_time: Optional[datetime]) -> int:
        """更新用户算力和过期时间"""
        sql = """
            UPDATE computing_power 
            SET computing_power = %s, expiration_time = %s, updated_at = NOW() 
            WHERE user_id = %s
        """
        try:
            return execute_update(sql, (computing_power, expiration_time, user_id))
        except Exception as e:
            logger.error(f"Failed to update computing power with expiration for user {user_id}: {e}")
            raise
    
    @staticmethod
    def delete(user_id: int) -> int:
        """删除算力记录"""
        sql = "DELETE FROM computing_power WHERE user_id = %s"
        try:
            return execute_update(sql, (user_id,))
        except Exception as e:
            logger.error(f"Failed to delete computing power for user {user_id}: {e}")
            raise
    
    @staticmethod
    def exists(user_id: int) -> bool:
        """检查用户是否已有算力记录"""
        sql = "SELECT COUNT(*) as count FROM computing_power WHERE user_id = %s"
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return result['count'] > 0 if result else False
        except Exception as e:
            logger.error(f"Failed to check computing power exists for user {user_id}: {e}")
            raise
    
    @staticmethod
    def ensure_exists(user_id: int) -> ComputingPower:
        """确保用户有算力记录，没有则创建（使用 create_or_update 避免并发问题）"""
        power = ComputingPowerModel.get_by_user_id(user_id)
        if not power:
            ComputingPowerModel.create_or_update(user_id, 0, None)
            power = ComputingPowerModel.get_by_user_id(user_id)
        return power
    
    # ==================== 管理员方法 ====================
    
    @staticmethod
    def admin_adjust(user_id: int, amount: int, reason: str) -> Tuple[int, int]:
        """
        管理员调整用户算力
        
        Args:
            user_id: 用户ID
            amount: 调整数量（正数增加，负数扣减）
            reason: 调整原因
        
        Returns:
            (原算力值, 新算力值) 元组
        """
        # 确保用户有算力记录
        power = ComputingPowerModel.ensure_exists(user_id)
        old_value = power.computing_power if power else 0
        new_value = max(0, old_value + amount)  # 确保算力不为负数
        
        # 更新算力
        ComputingPowerModel.update(user_id, new_value)
        logger.info(f"Admin adjusted computing power for user {user_id}: {old_value} -> {new_value}, reason: {reason}")
        
        # 记录到 computing_power_log
        try:
            # behavior 字段只能是 'increase' 或 'deduct'
            behavior = 'increase' if amount > 0 else 'deduct'
            ComputingPowerLogModel.create(
                user_id=user_id,
                behavior=behavior,
                computing_power=abs(amount),  # 使用绝对值
                from_value=old_value,
                to_value=new_value,
                message='管理员调整算力',
                note=reason
            )
        except Exception as e:
            logger.error(f"Failed to create computing power log for user {user_id}: {e}")
            # 不影响主流程，继续执行
        
        return (old_value, new_value)
