"""
统计缓存定时任务

定期计算并更新 implementation_stats_cache 表
"""
import logging
from model.implementation_attempts import ImplementationAttemptModel
from model.implementation_stats_cache import ImplementationStatsCacheModel

logger = logging.getLogger(__name__)


def refresh_implementation_stats_cache():
    """
    刷新实现方统计数据缓存

    从 implementation_attempts 表计算 7天 和 30天 两个时间范围的统计，
    并更新到 implementation_stats_cache 表。
    """
    logger.info("[StatsCache] Starting implementation stats cache refresh")

    # ⚠️ 非原子操作：先清除旧缓存再写入新缓存，中间存在窗口期（可能几十秒）
    # 缓存表中无数据。如果有 API 此时读取缓存，会得到空结果。
    # 此任务每小时执行一次，窗口期影响有限。
    for days in [7, 30]:
        try:
            ImplementationStatsCacheModel.clear_by_days(days)

            # 计算新统计（从 implementation_attempts 表）
            stats = ImplementationAttemptModel.get_stats(days)
            logger.info(f"[StatsCache] Calculated {len(stats)} records for {days}-day stats")

            # 写入缓存
            for row in stats:
                ImplementationStatsCacheModel.upsert(
                    task_type=row['type'],
                    impl_id=row['implementation'],
                    days=days,
                    total_count=row['total_count'],
                    success_count=row['success_count'],
                    fail_count=row['fail_count'],
                    success_rate=row['success_rate'],
                    avg_duration_ms=row['avg_duration_ms']
                )

            logger.info(f"[StatsCache] Successfully refreshed {days}-day stats cache with {len(stats)} records")

        except Exception as e:
            logger.error(f"[StatsCache] Failed to refresh {days}-day stats cache: {e}")
            import traceback
            logger.error(traceback.format_exc())

    logger.info("[StatsCache] Implementation stats cache refresh completed")
