"""
ImplementationStatsCache Model - 统计缓存表操作
"""
from typing import List, Dict, Any
from .database import execute_query, execute_update, execute_insert
import logging

logger = logging.getLogger(__name__)


class ImplementationStatsCacheModel:
    """统计缓存数据库操作"""

    @staticmethod
    def upsert(
        task_type: int,
        impl_id: int,
        days: int,
        total_count: int,
        success_count: int,
        fail_count: int,
        success_rate: float,
        avg_duration_ms: int
    ) -> bool:
        """
        插入或更新缓存记录

        Args:
            task_type: 任务类型ID
            impl_id: implementation ID
            days: 统计天数
            total_count: 总数
            success_count: 成功数
            fail_count: 失败数
            success_rate: 成功率
            avg_duration_ms: 平均耗时

        Returns:
            bool: 是否成功
        """
        sql = """
            INSERT INTO implementation_stats_cache
            (type, impl_id, days, total_count, success_count, fail_count, success_rate, avg_duration_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                total_count = VALUES(total_count),
                success_count = VALUES(success_count),
                fail_count = VALUES(fail_count),
                success_rate = VALUES(success_rate),
                avg_duration_ms = VALUES(avg_duration_ms),
                updated_at = CURRENT_TIMESTAMP
        """
        try:
            execute_update(sql, (task_type, impl_id, days, total_count, success_count, fail_count, success_rate, avg_duration_ms))
            return True
        except Exception as e:
            logger.error(f"Failed to upsert stats cache: {e}")
            return False

    @staticmethod
    def get_by_days(days: int) -> List[Dict[str, Any]]:
        """
        获取指定天数的缓存统计数据

        Args:
            days: 统计天数

        Returns:
            缓存记录列表
        """
        sql = """
            SELECT * FROM implementation_stats_cache
            WHERE days = %s
            ORDER BY total_count DESC
        """
        try:
            results = execute_query(sql, (days,), fetch_all=True)
            return results if results else []
        except Exception as e:
            logger.error(f"Failed to get stats cache: {e}")
            return []

    @staticmethod
    def get_latest_update_time(days: int) -> str:
        """
        获取指定天数缓存的最新更新时间

        Args:
            days: 统计天数

        Returns:
            最新更新时间字符串，格式为 ISO
        """
        sql = """
            SELECT MAX(updated_at) as latest FROM implementation_stats_cache
            WHERE days = %s
        """
        try:
            result = execute_query(sql, (days,), fetch_one=True)
            if result and result['latest']:
                return result['latest'].isoformat()
            return None
        except Exception as e:
            logger.error(f"Failed to get latest update time: {e}")
            return None

    @staticmethod
    def clear_by_days(days: int) -> int:
        """
        清除指定天数的缓存

        Args:
            days: 统计天数

        Returns:
            删除的记录数
        """
        sql = "DELETE FROM implementation_stats_cache WHERE days = %s"
        try:
            return execute_update(sql, (days,))
        except Exception as e:
            logger.error(f"Failed to clear stats cache: {e}")
            return 0


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `implementation_stats_cache` (
  `id` int NOT NULL AUTO_INCREMENT,
  `type` int NOT NULL COMMENT '任务类型ID',
  `impl_id` int NOT NULL COMMENT 'implementation ID',
  `days` int NOT NULL COMMENT '统计天数',
  `total_count` int NOT NULL DEFAULT '0',
  `success_count` int NOT NULL DEFAULT '0',
  `fail_count` int NOT NULL DEFAULT '0',
  `success_rate` decimal(5,2) NOT NULL DEFAULT '0.00',
  `avg_duration_ms` int NOT NULL DEFAULT '0',
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_type_impl_days` (`type`, `impl_id`, `days`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='实现统计缓存表';
"""
