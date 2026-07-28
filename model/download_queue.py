"""
Download Queue Model - 下载队列表的数据库操作

用于把"分钟级媒体下载"与"秒级状态机推进"解耦：visual_task 主循环检测到上游生成完成
后，把下载意图写入本表（ai_tools.status 置 DOWNLOADING），由独立的 download_queue_worker
job 异步消费。DB 是唯一真相源，服务重启后 pending 行与租约过期的 processing 行自动恢复。

设计要点：
- 幂等：UNIQUE(ai_tool_id) + ON DUPLICATE KEY UPDATE，同一任务不重复入队
- 抢占式认领：claim_pending 在事务内原子地置 status=1 + 写 worker_id/lease_until
- 租约回收：claim 同时回收 status=1 AND lease_until<NOW() 的崩溃遗留行（P1）
- 覆盖保护：旧行 status=1 时 IF 保护不覆盖（M1，避免打断正在处理的下载）
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from .database import execute_query, execute_update, transaction

logger = logging.getLogger(__name__)

# download_queue.status 取值
DQ_STATUS_PENDING = 0       # 待处理
DQ_STATUS_PROCESSING = 1    # 处理中（已 claim，持有租约）
DQ_STATUS_SUCCESS = 2       # 下载成功
DQ_STATUS_FAILED = -1       # 下载失败（已达 max_try，已用 remote_url 兜底 COMPLETED）

# enqueue 返回值（三态，M1）
ENQUEUE_NEW = "new"                      # 新插入，或重置了非处理中的旧行（before_finish 重试场景）
ENQUEUE_ALREADY_PROCESSING = "already"   # 旧行 status=1 正在处理，未覆盖；调用方不应 fallback


class DownloadQueueEntity:
    """download_queue 行实体"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.ai_tool_id = kwargs.get('ai_tool_id')
        self.task_id = kwargs.get('task_id')
        self.project_id = kwargs.get('project_id')
        self.remote_url = kwargs.get('remote_url')
        self.media_type = kwargs.get('media_type')
        self.status = kwargs.get('status')
        self.try_count = kwargs.get('try_count', 0) or 0
        self.max_try = kwargs.get('max_try', 3) or 3
        self.next_trigger = kwargs.get('next_trigger')
        self.result_url = kwargs.get('result_url')
        self.error_message = kwargs.get('error_message')
        self.worker_id = kwargs.get('worker_id')
        self.lease_until = kwargs.get('lease_until')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'ai_tool_id': self.ai_tool_id,
            'task_id': self.task_id,
            'project_id': self.project_id,
            'status': self.status,
            'try_count': self.try_count,
            'max_try': self.max_try,
            'remote_url': self.remote_url,
            'result_url': self.result_url,
            'error_message': self.error_message,
            'worker_id': self.worker_id,
            'next_trigger': str(self.next_trigger) if self.next_trigger else None,
            'lease_until': str(self.lease_until) if self.lease_until else None,
            'create_at': str(self.create_at) if self.create_at else None,
            'update_at': str(self.update_at) if self.update_at else None,
        }


class DownloadQueueModel:
    """download_queue 表操作"""

    @staticmethod
    def enqueue(
        ai_tool_id: int,
        task_id: str,
        remote_url: str,
        media_type: str = "video",
        project_id: Optional[str] = None,
        max_try: int = 3,
    ) -> str:
        """
        幂等入队（UNIQUE(ai_tool_id)）。

        - 全新：INSERT 一行 status=0
        - 旧行非处理中（status ∈ {0,2,-1}）：ON DUPLICATE 重置为 pending、覆盖新 URL/类型
          （before_finish 切换实现方重试复用同一 ai_tool_id，会命中此分支）
        - 旧行 status=1（正在处理）：IF 保护，不覆盖任何字段

        ⚠️ M1：本方法对"正在处理"返回 ENQUEUE_ALREADY_PROCESSING 而非抛异常，
           调用方据此判断"已有 worker 在干，无需 fallback 同步下载"。
           仅当 DB 异常时抛出，调用方 catch 后走同步下载兜底，确保任务不丢。

        Returns:
            ENQUEUE_NEW / ENQUEUE_ALREADY_PROCESSING
        """
        sql = """
            INSERT INTO download_queue
                (ai_tool_id, task_id, project_id, remote_url, media_type,
                 status, try_count, max_try, next_trigger, result_url, error_message,
                 worker_id, lease_until)
            VALUES
                (%s, %s, %s, %s, %s,
                 %s, %s, %s, NOW(), NULL, NULL, NULL, NULL)
            ON DUPLICATE KEY UPDATE
                status        = IF(status = 1, status, 0),
                try_count     = IF(status = 1, try_count, 0),
                max_try       = IF(status = 1, max_try, VALUES(max_try)),
                remote_url    = IF(status = 1, remote_url, VALUES(remote_url)),
                media_type    = IF(status = 1, media_type, VALUES(media_type)),
                project_id    = IF(status = 1, project_id, VALUES(project_id)),
                task_id       = IF(status = 1, task_id, VALUES(task_id)),
                next_trigger  = IF(status = 1, next_trigger, NOW()),
                result_url    = IF(status = 1, result_url, NULL),
                error_message = IF(status = 1, error_message, NULL),
                worker_id     = IF(status = 1, worker_id, NULL),
                lease_until   = IF(status = 1, lease_until, NULL)
        """
        params = (
            ai_tool_id, str(task_id), project_id, remote_url, media_type,
            DQ_STATUS_PENDING, 0, max_try,
        )
        try:
            execute_update(sql, params)
        except Exception as e:
            logger.error(f"enqueue download_queue failed ai_tool_id={ai_tool_id}: {e}")
            raise  # 调用方 catch → fallback 同步下载

        # 绕过 MySQL ON DUPLICATE rowcount 不可靠（UPDATE 但值未变返回 0），改为回查 status 判定
        row = execute_query(
            "SELECT status FROM download_queue WHERE ai_tool_id = %s",
            (ai_tool_id,),
            fetch_one=True,
        )
        if not row:
            raise RuntimeError(f"enqueue succeeded but row not found ai_tool_id={ai_tool_id}")
        if row['status'] == DQ_STATUS_PROCESSING:
            return ENQUEUE_ALREADY_PROCESSING
        return ENQUEUE_NEW

    @staticmethod
    def claim_pending(limit: int, lease_seconds: int, worker_id: str) -> List[Dict[str, Any]]:
        """
        原子化认领一批待处理行：置 status=1、写 worker_id / lease_until。

        同时把 status=1 且 lease_until<NOW() 的"崩溃 worker 遗留行"回收进来（P1）。
        事务 + SELECT ... FOR UPDATE 保证多实例下不重复认领（当前单实例下亦安全）。

        Args:
            limit: 最多认领行数
            lease_seconds: 租约时长（⚠️必须 > 下载超时 + 视频后处理预算 + 完成余量，否则
                           正在跑的完成路径会被下个 tick 误回收导致重复处理，见 M3）
            worker_id: 抢占标记（hostname-pid）

        Returns:
            认领到的行详情列表（dict，含全字段）
        """
        select_ids_sql = """
            SELECT id FROM download_queue
            WHERE (status = %s AND next_trigger <= NOW())
               OR (status = %s AND lease_until < NOW())
            ORDER BY next_trigger ASC
            LIMIT %s
            FOR UPDATE
        """
        try:
            with transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(select_ids_sql, (DQ_STATUS_PENDING, DQ_STATUS_PROCESSING, limit))
                rows = cursor.fetchall()
                if not rows:
                    return []
                ids = [r['id'] for r in rows]
                placeholders = ','.join(['%s'] * len(ids))
                update_sql = (
                    "UPDATE download_queue "
                    "SET status = %s, worker_id = %s, "
                    "lease_until = DATE_ADD(NOW(), INTERVAL %s SECOND), update_at = NOW() "
                    "WHERE id IN (" + placeholders + ")"
                )
                cursor.execute(
                    update_sql,
                    (DQ_STATUS_PROCESSING, worker_id, lease_seconds) + tuple(ids),
                )
                detail_sql = "SELECT * FROM download_queue WHERE id IN (" + placeholders + ")"
                cursor.execute(detail_sql, tuple(ids))
                return cursor.fetchall()
        except Exception as e:
            logger.error(f"claim_pending failed worker_id={worker_id}: {e}")
            raise

    @staticmethod
    def mark_success(row_id: int, result_url: str) -> int:
        """标记下载成功，清空抢占字段"""
        sql = (
            "UPDATE download_queue "
            "SET status = %s, result_url = %s, error_message = NULL, "
            "worker_id = NULL, lease_until = NULL, update_at = NOW() "
            "WHERE id = %s"
        )
        return execute_update(sql, (DQ_STATUS_SUCCESS, result_url, row_id))

    @staticmethod
    def mark_failed(row_id: int, error_message: str) -> int:
        """标记下载终结失败（已达 max_try，ai_tools 已用 remote_url 兜底 COMPLETED）"""
        sql = (
            "UPDATE download_queue "
            "SET status = %s, error_message = %s, "
            "worker_id = NULL, lease_until = NULL, update_at = NOW() "
            "WHERE id = %s"
        )
        return execute_update(sql, (DQ_STATUS_FAILED, error_message, row_id))

    @staticmethod
    def reschedule(row_id: int, try_count: int, next_trigger: datetime, error_message: str) -> int:
        """未达 max_try：退避后重新置 pending 等待下次 claim"""
        sql = (
            "UPDATE download_queue "
            "SET status = %s, try_count = %s, next_trigger = %s, error_message = %s, "
            "worker_id = NULL, lease_until = NULL, update_at = NOW() "
            "WHERE id = %s"
        )
        return execute_update(sql, (DQ_STATUS_PENDING, try_count, next_trigger, error_message, row_id))

    @staticmethod
    def get_by_ai_tool_id(ai_tool_id: int) -> Optional[DownloadQueueEntity]:
        sql = "SELECT * FROM download_queue WHERE ai_tool_id = %s LIMIT 1"
        row = execute_query(sql, (ai_tool_id,), fetch_one=True)
        return DownloadQueueEntity(**row) if row else None


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `download_queue` (
  `id` bigint NOT NULL AUTO_INCREMENT COMMENT 'Primary key',
  `ai_tool_id` bigint NOT NULL COMMENT '关联 ai_tools.id（幂等去重键）',
  `task_id` varchar(64) COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '冗余 task 标识(==ai_tool_id)，便于按 task 查',
  `project_id` varchar(128) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '冗余 project_id，worker 成功后按它更新 ai_tools',
  `remote_url` text COLLATE utf8mb4_unicode_ci NOT NULL COMMENT '待下载的远端 URL（唯一真相源）',
  `media_type` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'video' COMMENT 'image/video',
  `status` tinyint NOT NULL DEFAULT '0' COMMENT '0=待处理 1=处理中 2=成功 -1=失败(已兜底COMPLETED)',
  `try_count` int NOT NULL DEFAULT '0' COMMENT '已尝试次数',
  `max_try` int NOT NULL DEFAULT '3' COMMENT '最大尝试次数，达上限后用 remote_url 兜底',
  `next_trigger` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '下次可被 claim 的时间（退避用）',
  `result_url` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '下载成功后的本地/CDN URL',
  `error_message` text COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '最近一次失败原因',
  `worker_id` varchar(64) COLLATE utf8mb4_unicode_ci DEFAULT NULL COMMENT '抢占标记 hostname-pid（多实例防重）',
  `lease_until` datetime DEFAULT NULL COMMENT '租约到期时间；status=1 且到期则被回收',
  `create_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ai_tool_id` (`ai_tool_id`),
  KEY `idx_status_trigger` (`status`, `next_trigger`),
  KEY `idx_lease_until` (`status`, `lease_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='媒体下载队列：解耦主循环状态机推进与分钟级IO下载'
"""
