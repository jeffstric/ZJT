"""
实现方尝试记录 Model - 记录每次实现方尝试的成功/失败

用于准确统计各实现方的成功率和平均耗时，
解决重试机制覆盖 implementation 字段导致的统计偏差问题。
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from .database import execute_query, execute_update, execute_insert
import logging
import pymysql

logger = logging.getLogger(__name__)


# 尝试状态常量（与 ai_tools.status 对齐）
ATTEMPT_STATUS_IN_PROGRESS = 0
ATTEMPT_STATUS_SUCCESS = 2
ATTEMPT_STATUS_FAILED = -1


class ImplementationAttempt:
    """实现方尝试记录"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.ai_tool_id = kwargs.get('ai_tool_id')
        self.implementation = kwargs.get('implementation')
        self.attempt_number = kwargs.get('attempt_number', 1)
        self.status = kwargs.get('status', ATTEMPT_STATUS_IN_PROGRESS)
        self.error_message = kwargs.get('error_message')
        self.started_at = kwargs.get('started_at')
        self.completed_at = kwargs.get('completed_at')
        self.create_at = kwargs.get('create_at')


class ImplementationAttemptModel:
    """实现方尝试记录数据库操作"""

    @staticmethod
    def _build_date_filter(
        days: int,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        use_current_date: bool = False
    ) -> tuple:
        if start_date and end_date:
            return "a.create_at >= %s AND a.create_at < DATE_ADD(%s, INTERVAL 1 DAY)", [start_date, end_date]
        if start_date:
            return "a.create_at >= %s", [start_date]
        if end_date:
            return "a.create_at < DATE_ADD(%s, INTERVAL 1 DAY)", [end_date]

        interval_days = max(days - 1, 0) if use_current_date else days
        base_func = "CURDATE()" if use_current_date else "NOW()"
        return f"a.create_at >= DATE_SUB({base_func}, INTERVAL %s DAY)", [interval_days]

    @staticmethod
    def create(
        ai_tool_id: int,
        implementation: int,
        attempt_number: int = 1,
        status: int = ATTEMPT_STATUS_IN_PROGRESS,
        started_at: Optional[datetime] = None,
        error_message: Optional[str] = None
    ) -> int:
        """
        创建尝试记录

        Args:
            ai_tool_id: 关联 ai_tools.id
            implementation: 实现方 ID
            attempt_number: 第几次尝试（1=首次）
            status: 尝试状态
            started_at: 开始时间
            error_message: 失败原因

        Returns:
            插入的记录 ID
        """
        sql = """
            INSERT INTO implementation_attempts
            (ai_tool_id, implementation, attempt_number, status, started_at, error_message)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (ai_tool_id, implementation, attempt_number, status, started_at, error_message)

        try:
            record_id = execute_insert(sql, params)
            logger.debug(
                f"Created implementation attempt: id={record_id}, "
                f"ai_tool_id={ai_tool_id}, impl={implementation}, attempt={attempt_number}"
            )
            return record_id
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create implementation attempt: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to create implementation attempt (unexpected): {e}")
            raise

    @staticmethod
    def get_active_attempt(ai_tool_id: int) -> Optional[ImplementationAttempt]:
        """
        获取某任务当前正在进行的尝试（status=0）

        Args:
            ai_tool_id: ai_tools.id

        Returns:
            ImplementationAttempt 对象或 None
        """
        sql = """
            SELECT * FROM implementation_attempts
            WHERE ai_tool_id = %s AND status = %s
            ORDER BY attempt_number DESC
            LIMIT 1
        """
        try:
            result = execute_query(sql, (ai_tool_id, ATTEMPT_STATUS_IN_PROGRESS), fetch_one=True)
            return ImplementationAttempt(**result) if result else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get active attempt for ai_tool_id={ai_tool_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get active attempt for ai_tool_id={ai_tool_id} (unexpected): {e}")
            raise

    @staticmethod
    def mark_completed(
        record_id: int,
        status: int,
        error_message: Optional[str] = None,
        completed_at: Optional[datetime] = None
    ) -> int:
        """
        标记尝试完成

        Args:
            record_id: 记录 ID
            status: 最终状态（2=成功, -1=失败）
            error_message: 失败原因（可选）
            completed_at: 完成时间（默认当前时间）

        Returns:
            影响的行数
        """
        if completed_at is None:
            completed_at = datetime.now()

        update_fields = ["status = %s", "completed_at = %s"]
        params = [status, completed_at]

        if error_message is not None:
            update_fields.append("error_message = %s")
            params.append(error_message)

        params.append(record_id)
        sql = f"UPDATE implementation_attempts SET {', '.join(update_fields)} WHERE id = %s"

        try:
            affected = execute_update(sql, tuple(params))
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to mark attempt {record_id} as completed: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to mark attempt {record_id} as completed (unexpected): {e}")
            raise

    @staticmethod
    def mark_active_attempt_completed(
        ai_tool_id: int,
        status: int,
        error_message: Optional[str] = None
    ) -> bool:
        """
        便捷方法：标记某任务当前活跃的尝试为完成

        Args:
            ai_tool_id: ai_tools.id
            status: 最终状态
            error_message: 失败原因

        Returns:
            是否成功标记
        """
        try:
            attempt = ImplementationAttemptModel.get_active_attempt(ai_tool_id)
            if attempt:
                ImplementationAttemptModel.mark_completed(
                    attempt.id, status, error_message=error_message
                )
                return True
            else:
                logger.warning(f"No active attempt found for ai_tool_id={ai_tool_id}")
                return False
        except Exception as e:
            logger.error(f"Failed to mark active attempt completed for ai_tool_id={ai_tool_id}: {e}")
            return False

    @staticmethod
    def get_attempted_implementations(ai_tool_id: int) -> set:
        """
        获取某个 ai_tool 已经尝试过的所有实现方 ID

        Args:
            ai_tool_id: ai_tools.id

        Returns:
            已尝试的实现方 ID 集合
        """
        sql = "SELECT DISTINCT implementation FROM implementation_attempts WHERE ai_tool_id = %s"
        try:
            results = execute_query(sql, (ai_tool_id,), fetch_all=True)
            return {row['implementation'] for row in results} if results else set()
        except Exception as e:
            logger.error(f"Failed to get attempted implementations for ai_tool_id={ai_tool_id}: {e}")
            return set()

    @staticmethod
    def get_retry_implementation_count(ai_tool_id: int) -> int:
        """返回已登记的不同备用实现方数量（首次尝试 attempt_number=1 不计）。"""
        sql = """
            SELECT COUNT(DISTINCT implementation) AS retry_count
            FROM implementation_attempts
            WHERE ai_tool_id = %s AND attempt_number >= 2
        """
        try:
            result = execute_query(sql, (ai_tool_id,), fetch_one=True)
            if not result or result.get('retry_count') is None:
                return 0
            return int(result['retry_count'])
        except Exception as e:
            logger.error(
                "Failed to count retry implementations for ai_tool_id=%s: %s",
                ai_tool_id,
                e,
            )
            return 0

    @staticmethod
    def get_stats(days: int = 7, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取各实现方的统计数据（从 implementation_attempts 表）

        每次尝试独立记录，确保失败正确归因到实际失败的实现方。

        Args:
            days: 统计天数范围

        Returns:
            统计结果列表
        """
        date_filter, date_params = ImplementationAttemptModel._build_date_filter(days, start_date, end_date)
        sql = f"""
            SELECT
                t.type,
                a.implementation,
                COUNT(*) as total_count,
                SUM(CASE WHEN a.status = %s THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN a.status = %s THEN 1 ELSE 0 END) as fail_count,
                AVG(CASE WHEN a.completed_at IS NOT NULL AND a.started_at IS NOT NULL
                    THEN TIMESTAMPDIFF(MICROSECOND, a.started_at, a.completed_at) / 1000
                    ELSE NULL END) as avg_duration_ms
            FROM implementation_attempts a
            JOIN ai_tools t ON t.id = a.ai_tool_id
            WHERE {date_filter}
                AND a.status IN (%s, %s)
                AND a.implementation > 0
            GROUP BY t.type, a.implementation
            ORDER BY total_count DESC
        """

        try:
            results = execute_query(sql, (
                ATTEMPT_STATUS_SUCCESS,
                ATTEMPT_STATUS_FAILED,
                *date_params,
                ATTEMPT_STATUS_SUCCESS,
                ATTEMPT_STATUS_FAILED
            ), fetch_all=True)

            stats = []
            for row in results:
                total = int(row['total_count'])
                success_count = int(row['success_count']) if row['success_count'] else 0
                fail_count = int(row['fail_count']) if row['fail_count'] else 0
                success_rate = (success_count / total * 100) if total > 0 else 0.0

                stats.append({
                    'type': row['type'],
                    'implementation': row['implementation'],
                    'total_count': total,
                    'success_count': success_count,
                    'fail_count': fail_count,
                    'success_rate': round(success_rate, 2),
                    'avg_duration_ms': int(row['avg_duration_ms']) if row['avg_duration_ms'] else 0
                })
            return stats
        except Exception as e:
            logger.error(f"Failed to get implementation attempt stats: {e}")
            raise

    @staticmethod
    def get_daily_stats(days: int = 7, start_date: Optional[str] = None, end_date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取按天聚合的实现方统计数据。

        Args:
            days: 统计天数范围

        Returns:
            按日期、类型、实现方聚合的统计列表
        """
        date_filter, date_params = ImplementationAttemptModel._build_date_filter(
            days,
            start_date,
            end_date,
            use_current_date=True
        )
        sql = f"""
            SELECT
                DATE(a.create_at) as stat_date,
                t.type,
                a.implementation,
                COUNT(*) as total_count,
                SUM(CASE WHEN a.status = %s THEN 1 ELSE 0 END) as success_count,
                SUM(CASE WHEN a.status = %s THEN 1 ELSE 0 END) as fail_count
            FROM implementation_attempts a
            JOIN ai_tools t ON t.id = a.ai_tool_id
            WHERE {date_filter}
                AND a.status IN (%s, %s)
                AND a.implementation > 0
            GROUP BY DATE(a.create_at), t.type, a.implementation
            ORDER BY stat_date ASC, total_count DESC
        """

        try:
            results = execute_query(sql, (
                ATTEMPT_STATUS_SUCCESS,
                ATTEMPT_STATUS_FAILED,
                *date_params,
                ATTEMPT_STATUS_SUCCESS,
                ATTEMPT_STATUS_FAILED
            ), fetch_all=True)

            stats = []
            for row in results:
                total = int(row['total_count'])
                success_count = int(row['success_count']) if row['success_count'] else 0
                fail_count = int(row['fail_count']) if row['fail_count'] else 0
                success_rate = (success_count / total * 100) if total > 0 else 0.0
                stats.append({
                    'date': row['stat_date'].isoformat() if hasattr(row['stat_date'], 'isoformat') else str(row['stat_date']),
                    'type': row['type'],
                    'implementation': row['implementation'],
                    'total_count': total,
                    'success_count': success_count,
                    'fail_count': fail_count,
                    'success_rate': round(success_rate, 2)
                })
            return stats
        except Exception as e:
            logger.error(f"Failed to get daily implementation attempt stats: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `implementation_attempts` (
  `id` int NOT NULL AUTO_INCREMENT,
  `ai_tool_id` int NOT NULL COMMENT '关联 ai_tools.id',
  `implementation` int NOT NULL COMMENT '尝试的实现方 ID',
  `attempt_number` tinyint NOT NULL DEFAULT 1 COMMENT '第几次尝试 (1=首次)',
  `status` tinyint NOT NULL COMMENT '2=成功, -1=失败',
  `error_message` text DEFAULT NULL COMMENT '失败原因',
  `started_at` datetime DEFAULT NULL COMMENT '开始时间',
  `completed_at` datetime DEFAULT NULL COMMENT '完成时间',
  `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_ai_tool_id` (`ai_tool_id`),
  KEY `idx_impl_status_created` (`implementation`, `status`, `create_at`),
  KEY `idx_create_at` (`create_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='实现方尝试记录';
"""
