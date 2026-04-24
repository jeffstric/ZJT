"""
DailyCheckin Model - 每日签到记录数据库操作
"""
from typing import Optional, Dict, Any, List
from datetime import date, datetime
from .database import execute_query, execute_insert
import logging

logger = logging.getLogger(__name__)


class DailyCheckin:
    """DailyCheckin model class"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.checkin_date = kwargs.get('checkin_date')
        self.streak_days = kwargs.get('streak_days', 1)
        self.base_reward = kwargs.get('base_reward', 0)
        self.bonus_reward = kwargs.get('bonus_reward', 0)
        self.reward_amount = kwargs.get('reward_amount', 0)
        self.transaction_id = kwargs.get('transaction_id')
        self.created_at = kwargs.get('created_at')

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            'id': self.id,
            'user_id': self.user_id,
            'checkin_date': self.checkin_date.isoformat() if isinstance(self.checkin_date, (date, datetime)) else self.checkin_date,
            'streak_days': self.streak_days,
            'base_reward': self.base_reward,
            'bonus_reward': self.bonus_reward,
            'reward_amount': self.reward_amount,
            'transaction_id': self.transaction_id,
            'created_at': self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
        }


class DailyCheckinModel:
    """DailyCheckin database operations"""

    @staticmethod
    def create(
        user_id: int,
        checkin_date: date,
        streak_days: int,
        base_reward: int,
        bonus_reward: int,
        reward_amount: int,
        transaction_id: str
    ) -> int:
        """创建签到记录"""
        sql = """
            INSERT INTO daily_checkin
            (user_id, checkin_date, streak_days, base_reward, bonus_reward, reward_amount, transaction_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        try:
            record_id = execute_insert(sql, (
                user_id, checkin_date, streak_days,
                base_reward, bonus_reward, reward_amount, transaction_id
            ))
            logger.info(f"Created checkin record for user {user_id} on {checkin_date}, streak={streak_days}, reward={reward_amount}")
            return record_id
        except Exception as e:
            logger.error(f"Failed to create checkin record: {e}")
            raise

    @staticmethod
    def get_by_user_and_date(user_id: int, checkin_date: date) -> Optional[DailyCheckin]:
        """查询用户某天是否已签到"""
        sql = "SELECT * FROM daily_checkin WHERE user_id = %s AND checkin_date = %s"
        try:
            result = execute_query(sql, (user_id, checkin_date), fetch_one=True)
            return DailyCheckin(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get checkin for user {user_id} on {checkin_date}: {e}")
            raise

    @staticmethod
    def get_latest_by_user(user_id: int) -> Optional[DailyCheckin]:
        """获取用户最近一次签到记录"""
        sql = """
            SELECT * FROM daily_checkin
            WHERE user_id = %s
            ORDER BY checkin_date DESC
            LIMIT 1
        """
        try:
            result = execute_query(sql, (user_id,), fetch_one=True)
            return DailyCheckin(**result) if result else None
        except Exception as e:
            logger.error(f"Failed to get latest checkin for user {user_id}: {e}")
            raise

    @staticmethod
    def get_checkin_history(user_id: int, limit: int = 30, offset: int = 0) -> List[DailyCheckin]:
        """获取签到历史（分页）"""
        sql = """
            SELECT * FROM daily_checkin
            WHERE user_id = %s
            ORDER BY checkin_date DESC
            LIMIT %s OFFSET %s
        """
        try:
            results = execute_query(sql, (user_id, limit, offset), fetch_all=True)
            return [DailyCheckin(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to get checkin history for user {user_id}: {e}")
            raise

    @staticmethod
    def count_checkin_days(user_id: int, year: int, month: int) -> int:
        """统计某月签到天数"""
        sql = """
            SELECT COUNT(*) as count FROM daily_checkin
            WHERE user_id = %s AND YEAR(checkin_date) = %s AND MONTH(checkin_date) = %s
        """
        try:
            result = execute_query(sql, (user_id, year, month), fetch_one=True)
            return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Failed to count checkin days: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `daily_checkin` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL COMMENT '用户ID',
  `checkin_date` date NOT NULL COMMENT '签到日期',
  `streak_days` int NOT NULL DEFAULT 1 COMMENT '连续签到天数',
  `base_reward` int NOT NULL DEFAULT 0 COMMENT '基础奖励算力',
  `bonus_reward` int NOT NULL DEFAULT 0 COMMENT '连续签到额外奖励算力',
  `reward_amount` int NOT NULL DEFAULT 0 COMMENT '总奖励算力(基础+额外)',
  `transaction_id` varchar(100) DEFAULT NULL COMMENT '幂等交易ID',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '签到时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_date` (`user_id`, `checkin_date`),
  KEY `idx_user_created` (`user_id`, `created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='每日签到记录表';
"""
