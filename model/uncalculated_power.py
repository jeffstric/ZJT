"""
UncalculatedPower Model - 未扣减算力累积表
以 1/100 算力为最小刻度，累积满 100（即 1 算力）时扣减
"""
from typing import Optional
from datetime import datetime
from model.database import execute_query, execute_insert
import logging

logger = logging.getLogger(__name__)


class UncalculatedPower:
    """未扣减算力累积实体"""

    def __init__(
        self,
        id: int = 0,
        user_id: int = 0,
        accumulated_power: int = 0,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None
    ):
        self.id = id
        self.user_id = user_id
        self.accumulated_power = accumulated_power
        self.created_at = created_at
        self.updated_at = updated_at


class UncalculatedPowerModel:
    """未扣减算力累积数据库操作"""

    @staticmethod
    def get_by_user_id(user_id: int) -> Optional[UncalculatedPower]:
        """根据用户ID获取未扣减算力记录"""
        sql = """SELECT id, user_id, accumulated_power, created_at, updated_at
               FROM uncalculated_power WHERE user_id = %s"""
        try:
            row = execute_query(sql, (user_id,), fetch_one=True)
            if not row:
                return None
            return UncalculatedPower(
                id=row['id'],
                user_id=row['user_id'],
                accumulated_power=row['accumulated_power'],
                created_at=row['created_at'],
                updated_at=row['updated_at']
            )
        except Exception as e:
            logger.error(f"Failed to get uncalculated power for user {user_id}: {e}")
            raise

    @staticmethod
    def upsert(user_id: int, accumulated_power: int) -> int:
        """创建或更新用户的未扣减算力（百分位）"""
        sql = """INSERT INTO uncalculated_power (user_id, accumulated_power)
               VALUES (%s, %s)
               ON DUPLICATE KEY UPDATE accumulated_power = VALUES(accumulated_power)"""
        try:
            return execute_insert(sql, (user_id, accumulated_power))
        except Exception as e:
            logger.error(f"Failed to upsert uncalculated power for user {user_id}: {e}")
            raise
