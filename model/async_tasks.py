"""
Async Tasks Model - Database operations for async_tasks table
通用异步任务模型 - 支持多进程环境下的异步任务状态共享

参考 ai_tools 的 implementation 模式，通过 implementation (数字 ID) 区分不同的异步驱动，
每个驱动负责自己的 params 序列化/反序列化和业务逻辑。

⚠️ 与其他任务表的区别（易混淆，修改前请确认目标表）：
  - tasks: ComfyUI 视频/图片生成轮询队列，task_id 为 int（指向 ai_tools.id）
  - agent_tasks: Agent 对话任务（跨进程共享），task_id 为 UUID 字符串
  - async_tasks: 本表，外部服务异步任务（RunningHub 等），有 implementation 字段
  - grid_image_tasks: 宫格生图专用轮询，有 CANCELLED/DOWNLOAD_FAILED 状态
"""
from typing import List, Optional, Dict, Any
from .database import execute_query, execute_update, execute_insert
import logging
import json
import pymysql

logger = logging.getLogger(__name__)


class AsyncTaskStatus:
    """异步任务状态常量"""
    QUEUED = 0          # 队列中（已提交到外部服务）
    PROCESSING = 1      # 处理中（正在轮询）
    COMPLETED = 2       # 完成
    FAILED = -1         # 失败
    TIMEOUT = -2        # 超时


class AsyncTask:
    """异步任务模型"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.implementation = kwargs.get('implementation')
        self.external_task_id = kwargs.get('external_task_id')
        self.user_id = kwargs.get('user_id')
        self.params = kwargs.get('params')  # JSON 字符串或已解析的 dict
        self.status = kwargs.get('status', AsyncTaskStatus.QUEUED)
        self.try_count = kwargs.get('try_count', 0)
        self.max_attempts = kwargs.get('max_attempts', 60)
        self.error_message = kwargs.get('error_message')
        self.result_url = kwargs.get('result_url')
        self.result_data = kwargs.get('result_data')  # JSON 字符串或已解析的 dict
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.completed_at = kwargs.get('completed_at')
        self.failed_at = kwargs.get('failed_at')
        # 重试相关字段
        self.retry_count = kwargs.get('retry_count', 0)
        self.next_retry_at = kwargs.get('next_retry_at')
        self.max_retries = kwargs.get('max_retries', 5)

    def get_params_dict(self) -> Dict[str, Any]:
        """获取解析后的 params 字典"""
        if isinstance(self.params, dict):
            return self.params
        if isinstance(self.params, str):
            try:
                return json.loads(self.params)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse params as JSON: {self.params}")
                return {}
        return {}

    def get_result_data_dict(self) -> Dict[str, Any]:
        """获取解析后的 result_data 字典"""
        if isinstance(self.result_data, dict):
            return self.result_data
        if isinstance(self.result_data, str):
            try:
                return json.loads(self.result_data)
            except json.JSONDecodeError:
                return {}
        return {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'implementation': self.implementation,
            'external_task_id': self.external_task_id,
            'user_id': self.user_id,
            'params': self.get_params_dict(),
            'status': self.status,
            'try_count': self.try_count,
            'max_attempts': self.max_attempts,
            'error_message': self.error_message,
            'result_url': self.result_url,
            'result_data': self.get_result_data_dict(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'failed_at': self.failed_at.isoformat() if self.failed_at else None,
            'retry_count': self.retry_count,
            'next_retry_at': self.next_retry_at.isoformat() if self.next_retry_at else None,
            'max_retries': self.max_retries,
        }


class AsyncTasksModel:
    """异步任务数据库操作"""

    @staticmethod
    def create_and_schedule(
        implementation: int,
        user_id: int,
        params: Optional[Dict[str, Any]] = None,
        max_attempts: int = 60,
        max_retries: int = 5
    ) -> int:
        """
        创建异步任务并立即可被调度器拾取（next_retry_at = NOW()）

        适用于 API 端只需插入记录、由后台调度器统一处理提交的场景。
        """
        params_json = json.dumps(params) if params else None

        sql = """
            INSERT INTO async_tasks
            (implementation, user_id, params, status, max_attempts, next_retry_at, max_retries)
            VALUES (%s, %s, %s, %s, %s, NOW(), %s)
        """
        db_params = (
            implementation, user_id,
            params_json, AsyncTaskStatus.QUEUED, max_attempts, max_retries
        )

        try:
            record_id = execute_insert(sql, db_params)
            logger.info(f"Created and scheduled async task: id={record_id}, impl={implementation}")
            return record_id
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create and schedule async task: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to create and schedule async task (unexpected): {e}")
            raise

    @staticmethod
    def create(
        implementation: int,
        user_id: int,
        external_task_id: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
        max_attempts: int = 60
    ) -> int:
        """
        创建新的异步任务记录

        Args:
            implementation: 实现 ID（参考 AsyncTaskImplementationId 常量）
            user_id: 用户 ID
            external_task_id: 外部任务 ID（可选，如 RunningHub taskId）
            params: 任务参数（JSON 可序列化对象）
            max_attempts: 最大轮询次数

        Returns:
            插入的记录 ID
        """
        params_json = json.dumps(params) if params else None

        sql = """
            INSERT INTO async_tasks
            (implementation, user_id, external_task_id, params, status, max_attempts)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        db_params = (
            implementation, user_id, external_task_id,
            params_json, AsyncTaskStatus.QUEUED, max_attempts
        )

        try:
            record_id = execute_insert(sql, db_params)
            logger.info(f"Created async task: id={record_id}, implementation={implementation}")
            return record_id
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create async task: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to create async task (unexpected): {e}")
            raise

    @staticmethod
    def get_by_id(record_id: int) -> Optional[AsyncTask]:
        """根据 ID 获取任务"""
        sql = "SELECT * FROM async_tasks WHERE id = %s"
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            return AsyncTask(**result) if result else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get async task by id {record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get async task by id {record_id} (unexpected): {e}")
            raise

    @staticmethod
    def get_by_external_task_id(external_task_id: str) -> Optional[AsyncTask]:
        """根据外部任务 ID 获取任务"""
        sql = "SELECT * FROM async_tasks WHERE external_task_id = %s"
        try:
            result = execute_query(sql, (external_task_id,), fetch_one=True)
            return AsyncTask(**result) if result else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get async task by external_task_id {external_task_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get async task by external_task_id {external_task_id} (unexpected): {e}")
            raise

    @staticmethod
    def get_pending_tasks(implementation: Optional[int] = None, limit: int = 50) -> List[AsyncTask]:
        """
        获取待处理的任务（状态为 QUEUED 或 PROCESSING）

        Args:
            implementation: 实现 ID 筛选（可选，不传则获取所有实现的任务）
            limit: 最大返回数量

        Returns:
            AsyncTask 对象列表
        """
        if implementation:
            sql = """
                SELECT * FROM async_tasks
                WHERE implementation = %s AND status IN (%s, %s)
                ORDER BY created_at ASC
                LIMIT %s
            """
            params = (implementation, AsyncTaskStatus.QUEUED, AsyncTaskStatus.PROCESSING, limit)
        else:
            sql = """
                SELECT * FROM async_tasks
                WHERE status IN (%s, %s)
                ORDER BY created_at ASC
                LIMIT %s
            """
            params = (AsyncTaskStatus.QUEUED, AsyncTaskStatus.PROCESSING, limit)

        try:
            results = execute_query(sql, params, fetch_all=True)
            return [AsyncTask(**row) for row in results] if results else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get pending async tasks: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get pending async tasks (unexpected): {e}")
            raise

    @staticmethod
    def update_status(
        record_id: int,
        status: int,
        error_message: str = None,
        result_url: str = None,
        result_data: Dict[str, Any] = None
    ) -> int:
        """
        更新任务状态

        Args:
            record_id: 记录 ID
            status: 新状态
            error_message: 错误信息（可选）
            result_url: 结果 URL（可选）
            result_data: 额外结果数据（可选，JSON 可序列化对象）

        Returns:
            影响的行数
        """
        update_fields = ["status = %s"]
        params = [status]

        if error_message is not None:
            update_fields.append("error_message = %s")
            params.append(error_message)

        if result_url is not None:
            update_fields.append("result_url = %s")
            params.append(result_url)

        if result_data is not None:
            update_fields.append("result_data = %s")
            params.append(json.dumps(result_data))

        # 根据状态设置完成/失败时间
        if status == AsyncTaskStatus.COMPLETED:
            update_fields.append("completed_at = NOW()")
        elif status in (AsyncTaskStatus.FAILED, AsyncTaskStatus.TIMEOUT):
            update_fields.append("failed_at = NOW()")

        params.append(record_id)
        sql = f"UPDATE async_tasks SET {', '.join(update_fields)} WHERE id = %s"

        try:
            affected = execute_update(sql, tuple(params))
            logger.info(f"Updated async task {record_id} status to {status}")
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update async task {record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update async task {record_id} (unexpected): {e}")
            raise

    @staticmethod
    def increment_try_count(record_id: int) -> int:
        """增加任务尝试次数"""
        sql = "UPDATE async_tasks SET try_count = try_count + 1 WHERE id = %s"
        try:
            return execute_update(sql, (record_id,))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to increment try_count for id={record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to increment try_count for id={record_id} (unexpected): {e}")
            raise

    @staticmethod
    def update_external_task_id(record_id: int, external_task_id: str) -> int:
        """更新外部任务 ID"""
        sql = "UPDATE async_tasks SET external_task_id = %s WHERE id = %s"
        try:
            return execute_update(sql, (external_task_id, record_id))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update external_task_id for id={record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update external_task_id for id={record_id} (unexpected): {e}")
            raise

    @staticmethod
    def schedule_retry(record_id: int, delay_seconds: int) -> int:
        """
        安排任务重试（指数退避）

        Args:
            record_id: 记录 ID
            delay_seconds: 延迟秒数

        Returns:
            影响的行数
        """
        from datetime import datetime, timedelta
        next_retry_at = datetime.now() + timedelta(seconds=delay_seconds)

        sql = """
            UPDATE async_tasks
            SET retry_count = retry_count + 1,
                next_retry_at = %s
            WHERE id = %s
        """
        try:
            affected = execute_update(sql, (next_retry_at, record_id))
            logger.info(f"Async task {record_id} scheduled retry in {delay_seconds}s")
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to schedule retry for async task {record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to schedule retry for async task {record_id} (unexpected): {e}")
            raise

    @staticmethod
    def get_ready_to_retry_tasks(limit: int = 50) -> List['AsyncTask']:
        """
        获取可重试的任务（status=PENDING 且 next_retry_at <= NOW 且 retry_count < max_retries）

        Returns:
            AsyncTask 对象列表
        """
        sql = """
            SELECT * FROM async_tasks
            WHERE status = %s
              AND next_retry_at IS NOT NULL
              AND next_retry_at <= NOW()
              AND retry_count < max_retries
            ORDER BY next_retry_at ASC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (AsyncTaskStatus.QUEUED, limit), fetch_all=True)
            return [AsyncTask(**row) for row in results] if results else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get ready-to-retry tasks: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get ready-to-retry tasks (unexpected): {e}")
            raise

    @staticmethod
    def update_status_with_retry(
        record_id: int,
        status: int,
        error_message: str = None,
        result_url: str = None,
        result_data: Dict[str, Any] = None,
        reset_retry: bool = False
    ) -> int:
        """
        更新任务状态，可选重置重试计数

        Args:
            record_id: 记录 ID
            status: 新状态
            error_message: 错误信息（可选）
            result_url: 结果 URL（可选）
            result_data: 额外结果数据（可选）
            reset_retry: 是否重置重试计数（默认 False）

        Returns:
            影响的行数
        """
        update_fields = ["status = %s"]
        params = [status]

        if error_message is not None:
            update_fields.append("error_message = %s")
            params.append(error_message)

        if result_url is not None:
            update_fields.append("result_url = %s")
            params.append(result_url)

        if result_data is not None:
            update_fields.append("result_data = %s")
            params.append(json.dumps(result_data))

        if reset_retry:
            update_fields.append("retry_count = 0")
            update_fields.append("next_retry_at = NULL")

        # 根据状态设置完成/失败时间
        if status == AsyncTaskStatus.COMPLETED:
            update_fields.append("completed_at = NOW()")
        elif status in (AsyncTaskStatus.FAILED, AsyncTaskStatus.TIMEOUT):
            update_fields.append("failed_at = NOW()")

        params.append(record_id)
        sql = f"UPDATE async_tasks SET {', '.join(update_fields)} WHERE id = %s"

        try:
            affected = execute_update(sql, tuple(params))
            logger.info(f"Updated async task {record_id} status to {status}")
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update async task {record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update async task {record_id} (unexpected): {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `async_tasks` (
  `id` int NOT NULL AUTO_INCREMENT COMMENT '主键ID',
  `implementation` int unsigned NOT NULL DEFAULT '0' COMMENT '实现 ID（参考 AsyncTaskImplementationId）',
  `external_task_id` varchar(100) DEFAULT NULL COMMENT '外部任务 ID（如 RunningHub taskId）',
  `user_id` int NOT NULL COMMENT '用户 ID',
  `params` json DEFAULT NULL COMMENT '任务参数（JSON 格式，implementation 特定）',
  `status` tinyint DEFAULT '0' COMMENT '状态（0-队列中, 1-处理中, 2-完成, -1-失败, -2-超时）',
  `try_count` int DEFAULT '0' COMMENT '轮询尝试次数',
  `max_attempts` int DEFAULT '60' COMMENT '最大尝试次数',
  `error_message` text COMMENT '错误信息',
  `result_url` varchar(1000) DEFAULT NULL COMMENT '结果 URL',
  `result_data` json DEFAULT NULL COMMENT '额外结果数据（JSON 格式）',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `completed_at` datetime DEFAULT NULL COMMENT '完成时间',
  `failed_at` datetime DEFAULT NULL COMMENT '失败时间',
  `retry_count` int DEFAULT '0' COMMENT '重试次数',
  `next_retry_at` datetime DEFAULT NULL COMMENT '下次重试时间',
  `max_retries` int DEFAULT '5' COMMENT '最大重试次数',
  PRIMARY KEY (`id`),
  KEY `idx_user_id` (`user_id`),
  KEY `idx_impl_status` (`implementation`, `status`),
  KEY `idx_async_task_retry_ready` (`status`, `next_retry_at`, `retry_count`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='通用异步任务表';
"""
