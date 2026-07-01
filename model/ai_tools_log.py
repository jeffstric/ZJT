"""
AI Tools Log Model - 每个 ai_tools 任务的全生命周期事件日志（只增不改）

用于排查任务耗时、轮询静默、卡死等问题。每个关键事件（含每次状态轮询）写一行，
可通过 ai_tool_id 或冗余的 project_id 直接定位完整时间线。

设计原则：
- 只增不改（append-only）：永不 UPDATE/DELETE
- best-effort：log() 永不抛异常，观测失败不影响任务主流程
- 独立连接单条 INSERT：不并入业务事务，避免随业务回滚
"""
from typing import List, Optional, Dict, Any
from .database import execute_query, execute_insert
import logging
import json
import pymysql

logger = logging.getLogger(__name__)


class AIToolsLogEvent:
    """事件类型常量（字符串，便于直接阅读与过滤）"""
    RECORD_CREATED = 'record_created'                  # ai_tools 记录创建
    TASK_STARTED = 'task_started'                      # 调度器接管，status→PROCESSING
    SLOT_DELAYED = 'slot_delayed'                      # RunningHub 槽位已满，延迟
    IMPLEMENTATION_SELECTED = 'implementation_selected'  # 选用驱动/实现方
    SUBMITTED = 'submitted'                            # 提交到上游，拿到 project_id
    STATUS_CHECK = 'status_check'                      # 每次状态轮询（含 running）
    UPSTREAM_SUCCEEDED = 'upstream_succeeded'          # 上游返回成功，拿到结果 URL
    UPSTREAM_FAILED = 'upstream_failed'                # 上游返回失败/错误
    DOWNLOAD_STARTED = 'download_started'              # 开始下载结果文件
    DOWNLOAD_COMPLETED = 'download_completed'          # 下载/缓存完成
    CDN_UPLOADED = 'cdn_uploaded'                      # 七牛 CDN 上传完成
    RETRY_SCHEDULED = 'retry_scheduled'                # 失败，安排重试（next_trigger）
    MAX_RETRY_EXCEEDED = 'max_retry_exceeded'          # 超过最大重试次数，终态失败
    TASK_COMPLETED = 'task_completed'                  # 任务终态成功
    EXCEPTION = 'exception'                            # 流程中出现未预期异常
    PIPELINE_STEP = 'pipeline_step'                    # 流水线步骤事件（预留）


class AIToolsLog:
    """事件日志记录"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.ai_tool_id = kwargs.get('ai_tool_id')
        self.user_id = kwargs.get('user_id')
        self.project_id = kwargs.get('project_id')
        self.event_type = kwargs.get('event_type')
        self.status_from = kwargs.get('status_from')
        self.status_to = kwargs.get('status_to')
        self.implementation = kwargs.get('implementation')
        self.try_count = kwargs.get('try_count')
        self.message = kwargs.get('message')
        self.detail = kwargs.get('detail')
        self.duration_ms = kwargs.get('duration_ms')
        self.create_at = kwargs.get('create_at')

    def get_detail_dict(self) -> Dict[str, Any]:
        """获取解析后的 detail 字典"""
        if isinstance(self.detail, dict):
            return self.detail
        if isinstance(self.detail, str):
            try:
                return json.loads(self.detail)
            except json.JSONDecodeError:
                return {}
        return {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'ai_tool_id': self.ai_tool_id,
            'user_id': self.user_id,
            'project_id': self.project_id,
            'event_type': self.event_type,
            'status_from': self.status_from,
            'status_to': self.status_to,
            'implementation': self.implementation,
            'try_count': self.try_count,
            'message': self.message,
            'detail': self.get_detail_dict(),
            'duration_ms': self.duration_ms,
            'create_at': self.create_at.isoformat() if self.create_at else None,
        }


class AIToolsLogModel:
    """事件日志数据库操作"""

    @staticmethod
    def log(
        ai_tool_id: Optional[int],
        event_type: str,
        *,
        project_id: Optional[str] = None,
        user_id: Optional[int] = None,
        implementation: Optional[int] = None,
        try_count: Optional[int] = None,
        status_from: Optional[int] = None,
        status_to: Optional[int] = None,
        message: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None
    ) -> None:
        """
        写入一条事件日志（best-effort，永不抛异常）

        使用独立连接、独立提交，不并入任何业务事务，避免随业务回滚；
        任何写入异常仅记录 debug 日志，绝不影响任务主流程。

        Args:
            ai_tool_id: 关联 ai_tools.id（允许 None，极端情况下也能写入）
            event_type: 事件类型（见 AIToolsLogEvent）
            project_id: 冗余上游任务ID
            user_id: 冗余用户ID
            implementation: 冗余实现方ID
            try_count: 冗余重试次数
            status_from/status_to: ai_tools.status 变更前后
            message: 简短描述（最长 500）
            detail: 详细上下文（JSON 可序列化对象）
            duration_ms: 本事件耗时（毫秒）
        """
        if ai_tool_id is None and not project_id:
            # 既无 ai_tool_id 又无 project_id，无法关联，直接放弃
            logger.debug(f"Skip ai_tools_log: no ai_tool_id/project_id, event={event_type}")
            return

        # 截断 message，避免超长
        if message and len(message) > 500:
            message = message[:497] + '...'

        detail_json = json.dumps(detail, ensure_ascii=False, default=str) if detail else None

        sql = """
            INSERT INTO ai_tools_log
            (ai_tool_id, user_id, project_id, event_type, status_from, status_to,
             implementation, try_count, message, detail, duration_ms)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            ai_tool_id, user_id, project_id, event_type,
            status_from, status_to, implementation, try_count,
            message, detail_json, duration_ms
        )

        try:
            execute_insert(sql, params)
        except pymysql.MySQLError as e:
            logger.debug(f"Failed to write ai_tools_log (event={event_type}, ai_tool_id={ai_tool_id}): {e}")
        except Exception as e:
            logger.debug(f"Failed to write ai_tools_log (unexpected, event={event_type}, ai_tool_id={ai_tool_id}): {e}")

    @staticmethod
    def list_by_ai_tool(ai_tool_id: int, limit: int = 1000) -> List[AIToolsLog]:
        """
        按任务 ID 获取事件时间线（按时间升序）

        Args:
            ai_tool_id: ai_tools.id
            limit: 最大返回数量

        Returns:
            AIToolsLog 对象列表（升序）
        """
        sql = """
            SELECT * FROM ai_tools_log
            WHERE ai_tool_id = %s
            ORDER BY create_at ASC, id ASC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (ai_tool_id, limit), fetch_all=True)
            return [AIToolsLog(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to list ai_tools_log for ai_tool_id={ai_tool_id}: {e}")
            raise

    @staticmethod
    def list_by_project_id(project_id: str, limit: int = 1000) -> List[AIToolsLog]:
        """
        按上游 project_id 获取事件时间线（按时间升序）

        便于排查时直接用 Duomi 等上游返回的任务 ID 定位，无需先查 ai_tools。

        Args:
            project_id: 上游任务 ID
            limit: 最大返回数量

        Returns:
            AIToolsLog 对象列表（升序）
        """
        sql = """
            SELECT * FROM ai_tools_log
            WHERE project_id = %s
            ORDER BY create_at ASC, id ASC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (project_id, limit), fetch_all=True)
            return [AIToolsLog(**row) for row in results] if results else []
        except Exception as e:
            logger.error(f"Failed to list ai_tools_log for project_id={project_id}: {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `ai_tools_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `ai_tool_id` int NOT NULL COMMENT '关联 ai_tools.id',
  `user_id` int DEFAULT NULL COMMENT '冗余 user_id，便于按用户排查',
  `project_id` varchar(100) DEFAULT NULL COMMENT '冗余上游任务ID（Duomi 等），可直接定位',
  `event_type` varchar(48) NOT NULL COMMENT '事件类型，见 AIToolsLogEvent',
  `status_from` tinyint DEFAULT NULL COMMENT '变更前 ai_tools.status',
  `status_to` tinyint DEFAULT NULL COMMENT '变更后 ai_tools.status',
  `implementation` int DEFAULT NULL COMMENT '冗余实现方ID',
  `try_count` int DEFAULT NULL COMMENT '冗余重试次数',
  `message` varchar(500) DEFAULT NULL COMMENT '简短描述',
  `detail` json DEFAULT NULL COMMENT '详细上下文（上游响应/URL/耗时等）',
  `duration_ms` int DEFAULT NULL COMMENT '本事件耗时(毫秒)，如下载/上传耗时',
  `create_at` timestamp(3) NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '事件发生时间(毫秒精度)',
  PRIMARY KEY (`id`),
  KEY `idx_atool_create` (`ai_tool_id`,`create_at`),
  KEY `idx_project_id` (`project_id`),
  KEY `idx_event_create` (`event_type`,`create_at`),
  KEY `idx_create_at` (`create_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI工具任务事件日志（只增不改，排查用）';
"""
