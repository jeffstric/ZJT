"""
AI Tool Pipeline Steps Model - Database operations for ai_tool_pipeline_steps table

流水线步骤模型 - 支持在 ai_tools 处理流程中插入预处理（param_prepare）和结束前处理（before_finish）步骤。
每个 ai_tool 可关联多个步骤（多对一），由 PipelineProcessor 编排执行。
"""
from typing import List, Optional, Dict, Any
from .database import execute_query, execute_update, execute_insert
import logging
import json
import pymysql

logger = logging.getLogger(__name__)


class PipelineStepStatus:
    """流水线步骤状态常量"""
    PENDING = 0          # 待处理
    PROCESSING = 1       # 处理中
    COMPLETED = 2        # 完成
    FAILED = -1          # 失败
    TIMEOUT = -2         # 超时


class PipelineStage:
    """流水线阶段常量"""
    PARAM_PREPARE = 'param_prepare'      # 参数预处理阶段
    BEFORE_FINISH = 'before_finish'      # 结束前处理阶段


class PipelineStepType:
    """流水线步骤类型常量"""
    FACE_MASK = 'face_mask'                        # 人脸遮盖
    IMAGE_FACE_MASK = 'image_face_mask'            # 图片人脸遮盖
    IMPLEMENTATION_RETRY = 'implementation_retry'  # 实现方重试
    STORYBOARD_FIRST_FRAME_GRID_SPLIT = 'storyboard_first_frame_grid_split'


class PipelineStep:
    """流水线步骤模型"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.ai_tool_id = kwargs.get('ai_tool_id')
        self.stage = kwargs.get('stage')
        self.step_type = kwargs.get('step_type')
        self.target = kwargs.get('target')
        self.step_order = kwargs.get('step_order', 0)
        self.status = kwargs.get('status', PipelineStepStatus.PENDING)
        self.params = kwargs.get('params')
        self.result_data = kwargs.get('result_data')
        self.result_url = kwargs.get('result_url')
        self.error_message = kwargs.get('error_message')
        self.async_task_id = kwargs.get('async_task_id')
        self.retry_count = kwargs.get('retry_count', 0)
        self.next_retry_at = kwargs.get('next_retry_at')
        self.max_retries = kwargs.get('max_retries', 5)
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')
        self.completed_at = kwargs.get('completed_at')

    def get_params_dict(self) -> Dict[str, Any]:
        """获取解析后的 params 字典"""
        if isinstance(self.params, dict):
            return self.params
        if isinstance(self.params, str):
            try:
                return json.loads(self.params)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse pipeline step params: {self.params}")
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
            'ai_tool_id': self.ai_tool_id,
            'stage': self.stage,
            'step_type': self.step_type,
            'target': self.target,
            'step_order': self.step_order,
            'status': self.status,
            'params': self.get_params_dict(),
            'result_data': self.get_result_data_dict(),
            'result_url': self.result_url,
            'error_message': self.error_message,
            'async_task_id': self.async_task_id,
            'retry_count': self.retry_count,
            'next_retry_at': self.next_retry_at.isoformat() if self.next_retry_at else None,
            'max_retries': self.max_retries,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


class PipelineStepModel:
    """流水线步骤数据库操作"""

    @staticmethod
    def create(
        ai_tool_id: int,
        stage: str,
        step_type: str,
        step_order: int = 0,
        params: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None
    ) -> int:
        """
        创建流水线步骤

        Args:
            ai_tool_id: 关联的 ai_tools.id
            stage: 阶段（param_prepare / before_finish）
            step_type: 步骤类型（face_mask / implementation_retry）
            step_order: 同阶段内执行顺序（0 起始）
            params: 步骤参数（JSON 可序列化对象）
            target: 步骤目标（如对应的 video_path）

        Returns:
            插入的记录 ID
        """
        params_json = json.dumps(params) if params else None

        sql = """
            INSERT INTO ai_tool_pipeline_steps
            (ai_tool_id, stage, step_type, target, step_order, status, params)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        db_params = (ai_tool_id, stage, step_type, target, step_order, PipelineStepStatus.PENDING, params_json)

        try:
            record_id = execute_insert(sql, db_params)
            logger.info(f"Created pipeline step: id={record_id}, ai_tool_id={ai_tool_id}, stage={stage}, type={step_type}")
            return record_id
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create pipeline step: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to create pipeline step (unexpected): {e}")
            raise

    @staticmethod
    def create_in_transaction(
        conn,
        ai_tool_id: int,
        stage: str,
        step_type: str,
        step_order: int = 0,
        params: Optional[Dict[str, Any]] = None,
        target: Optional[str] = None
    ) -> int:
        """
        在指定事务连接中创建流水线步骤（不自动 commit）

        Args:
            conn: transaction() 上下文中的数据库连接
            ai_tool_id: 关联的 ai_tools.id
            stage: 阶段（param_prepare / before_finish）
            step_type: 步骤类型（face_mask / implementation_retry）
            step_order: 同阶段内执行顺序（0 起始）
            params: 步骤参数（JSON 可序列化对象）
            target: 步骤目标（如对应的 video_path）

        Returns:
            插入的记录 ID
        """
        from .database import execute_insert_in_transaction as _exec_insert
        params_json = json.dumps(params) if params else None

        sql = """
            INSERT INTO ai_tool_pipeline_steps
            (ai_tool_id, stage, step_type, target, step_order, status, params)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        db_params = (ai_tool_id, stage, step_type, target, step_order, PipelineStepStatus.PENDING, params_json)

        try:
            record_id = _exec_insert(conn, sql, db_params)
            logger.info(f"Created pipeline step (in transaction): id={record_id}, ai_tool_id={ai_tool_id}, stage={stage}, type={step_type}, target={target}")
            return record_id
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create pipeline step in transaction: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to create pipeline step in transaction (unexpected): {e}")
            raise

    @staticmethod
    def get_by_id(record_id: int) -> Optional[PipelineStep]:
        """根据 ID 获取步骤"""
        sql = "SELECT * FROM ai_tool_pipeline_steps WHERE id = %s"
        try:
            result = execute_query(sql, (record_id,), fetch_one=True)
            return PipelineStep(**result) if result else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get pipeline step by id {record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get pipeline step by id {record_id} (unexpected): {e}")
            raise

    @staticmethod
    def get_by_ai_tool_and_stage(ai_tool_id: int, stage: str) -> List[PipelineStep]:
        """
        获取某 ai_tool 某阶段的所有步骤（按 step_order 排序）

        Args:
            ai_tool_id: ai_tools.id
            stage: 阶段名称

        Returns:
            PipelineStep 对象列表
        """
        sql = """
            SELECT * FROM ai_tool_pipeline_steps
            WHERE ai_tool_id = %s AND stage = %s
            ORDER BY step_order ASC
        """
        try:
            results = execute_query(sql, (ai_tool_id, stage), fetch_all=True)
            return [PipelineStep(**row) for row in results] if results else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get pipeline steps for ai_tool_id={ai_tool_id}, stage={stage}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get pipeline steps for ai_tool_id={ai_tool_id}, stage={stage} (unexpected): {e}")
            raise

    @staticmethod
    def get_pending_steps(ai_tool_id: int, stage: str) -> List[PipelineStep]:
        """
        获取某 ai_tool 某阶段的待处理步骤（status=PENDING，按 step_order 排序）

        Args:
            ai_tool_id: ai_tools.id
            stage: 阶段名称

        Returns:
            PipelineStep 对象列表
        """
        sql = """
            SELECT * FROM ai_tool_pipeline_steps
            WHERE ai_tool_id = %s AND stage = %s AND status = %s
            ORDER BY step_order ASC
        """
        try:
            results = execute_query(sql, (ai_tool_id, stage, PipelineStepStatus.PENDING), fetch_all=True)
            return [PipelineStep(**row) for row in results] if results else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get pending pipeline steps: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get pending pipeline steps (unexpected): {e}")
            raise

    @staticmethod
    def get_processing_steps(limit: int = 50) -> List[PipelineStep]:
        """
        获取所有处理中的步骤（调度器轮询用）

        Args:
            limit: 最大返回数量

        Returns:
            PipelineStep 对象列表
        """
        sql = """
            SELECT * FROM ai_tool_pipeline_steps
            WHERE status = %s
            ORDER BY created_at ASC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (PipelineStepStatus.PROCESSING, limit), fetch_all=True)
            return [PipelineStep(**row) for row in results] if results else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get processing pipeline steps: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get processing pipeline steps (unexpected): {e}")
            raise

    @staticmethod
    def get_all_waiting_steps(limit: int = 100) -> List[PipelineStep]:
        """
        获取所有 PENDING 状态的步骤（调度器分发用）

        Args:
            limit: 最大返回数量

        Returns:
            PipelineStep 对象列表
        """
        sql = """
            SELECT * FROM ai_tool_pipeline_steps
            WHERE status = %s
            ORDER BY created_at ASC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (PipelineStepStatus.PENDING, limit), fetch_all=True)
            return [PipelineStep(**row) for row in results] if results else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get waiting pipeline steps: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get waiting pipeline steps (unexpected): {e}")
            raise

    @staticmethod
    def update_status(
        record_id: int,
        status: int,
        error_message: Optional[str] = None,
        result_data: Optional[Dict[str, Any]] = None,
        result_url: Optional[str] = None
    ) -> int:
        """
        更新步骤状态

        Args:
            record_id: 记录 ID
            status: 新状态
            error_message: 错误信息（可选）
            result_data: 结果数据（可选，JSON 可序列化对象）
            result_url: 结果文件路径（可选）

        Returns:
            影响的行数
        """
        update_fields = ["status = %s"]
        params = [status]

        if error_message is not None:
            update_fields.append("error_message = %s")
            params.append(error_message)

        if result_data is not None:
            update_fields.append("result_data = %s")
            params.append(json.dumps(result_data))

        if result_url is not None:
            update_fields.append("result_url = %s")
            params.append(result_url)

        if status in (PipelineStepStatus.COMPLETED,):
            update_fields.append("completed_at = NOW()")

        params.append(record_id)
        sql = f"UPDATE ai_tool_pipeline_steps SET {', '.join(update_fields)} WHERE id = %s"

        try:
            affected = execute_update(sql, tuple(params))
            logger.info(f"Updated pipeline step {record_id} status to {status}")
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update pipeline step {record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update pipeline step {record_id} (unexpected): {e}")
            raise

    @staticmethod
    def update_status_with_retry(
        record_id: int,
        status: int,
        error_message: Optional[str] = None,
        result_data: Optional[Dict[str, Any]] = None,
        reset_retry: bool = False,
        result_url: Optional[str] = None
    ) -> int:
        """
        更新步骤状态，可选重置重试计数

        Args:
            record_id: 记录 ID
            status: 新状态
            error_message: 错误信息（可选）
            result_data: 结果数据（可选，JSON 可序列化对象）
            reset_retry: 是否重置重试计数
            result_url: 结果文件路径（可选）

        Returns:
            影响的行数
        """
        update_fields = ["status = %s"]
        params = [status]

        if error_message is not None:
            update_fields.append("error_message = %s")
            params.append(error_message)

        if result_data is not None:
            update_fields.append("result_data = %s")
            params.append(json.dumps(result_data))

        if result_url is not None:
            update_fields.append("result_url = %s")
            params.append(result_url)

        if reset_retry:
            update_fields.append("retry_count = 0")
            update_fields.append("next_retry_at = NULL")

        if status == PipelineStepStatus.COMPLETED:
            update_fields.append("completed_at = NOW()")

        params.append(record_id)
        sql = f"UPDATE ai_tool_pipeline_steps SET {', '.join(update_fields)} WHERE id = %s"

        try:
            affected = execute_update(sql, tuple(params))
            logger.info(f"Updated pipeline step {record_id} status to {status} (reset_retry={reset_retry})")
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update pipeline step {record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update pipeline step {record_id} (unexpected): {e}")
            raise

    @staticmethod
    def schedule_retry(record_id: int, delay_seconds: int) -> int:
        """
        安排步骤重试（指数退避）

        Args:
            record_id: 记录 ID
            delay_seconds: 延迟秒数

        Returns:
            影响的行数
        """
        from datetime import datetime, timedelta
        next_retry_at = datetime.now() + timedelta(seconds=delay_seconds)

        sql = """
            UPDATE ai_tool_pipeline_steps
            SET retry_count = retry_count + 1,
                next_retry_at = %s
            WHERE id = %s
        """
        try:
            affected = execute_update(sql, (next_retry_at, record_id))
            logger.info(f"Pipeline step {record_id} scheduled retry in {delay_seconds}s")
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to schedule retry for step {record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to schedule retry for step {record_id} (unexpected): {e}")
            raise

    @staticmethod
    def get_ready_to_retry_steps(limit: int = 50) -> List[PipelineStep]:
        """
        获取可重试的步骤（next_retry_at <= NOW 且 retry_count < max_retries）

        Args:
            limit: 最大返回数量

        Returns:
            PipelineStep 对象列表
        """
        sql = """
            SELECT * FROM ai_tool_pipeline_steps
            WHERE status = %s
              AND next_retry_at IS NOT NULL
              AND next_retry_at <= NOW()
              AND retry_count < max_retries
            ORDER BY next_retry_at ASC
            LIMIT %s
        """
        try:
            results = execute_query(sql, (PipelineStepStatus.PENDING, limit), fetch_all=True)
            return [PipelineStep(**row) for row in results] if results else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get ready-to-retry steps: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get ready-to-retry steps (unexpected): {e}")
            raise

    @staticmethod
    def update_async_task_id(record_id: int, async_task_id: int) -> int:
        """关联 async_task"""
        sql = "UPDATE ai_tool_pipeline_steps SET async_task_id = %s WHERE id = %s"
        try:
            return execute_update(sql, (async_task_id, record_id))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update async_task_id for pipeline step {record_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update async_task_id for pipeline step {record_id} (unexpected): {e}")
            raise

    @staticmethod
    def has_steps(ai_tool_id: int, stage: str) -> bool:
        """检查某 ai_tool 某阶段是否存在步骤（不限状态）"""
        sql = """
            SELECT COUNT(*) as cnt FROM ai_tool_pipeline_steps
            WHERE ai_tool_id = %s AND stage = %s
        """
        try:
            result = execute_query(sql, (ai_tool_id, stage), fetch_one=True)
            return result and result['cnt'] > 0
        except pymysql.MySQLError as e:
            logger.error(f"Failed to check pipeline steps for ai_tool_id={ai_tool_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to check pipeline steps for ai_tool_id={ai_tool_id} (unexpected): {e}")
            raise

    @staticmethod
    def delete_by_ai_tool_id(ai_tool_id: int) -> int:
        """删除某 ai_tool 的所有步骤"""
        sql = "DELETE FROM ai_tool_pipeline_steps WHERE ai_tool_id = %s"
        try:
            affected = execute_update(sql, (ai_tool_id,))
            logger.info(f"Deleted {affected} pipeline steps for ai_tool_id={ai_tool_id}")
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to delete pipeline steps for ai_tool_id={ai_tool_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to delete pipeline steps for ai_tool_id={ai_tool_id} (unexpected): {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `ai_tool_pipeline_steps` (
  `id` int NOT NULL AUTO_INCREMENT,
  `ai_tool_id` int NOT NULL COMMENT '关联 ai_tools.id',
  `stage` varchar(32) NOT NULL COMMENT '阶段: param_prepare | before_finish',
  `step_type` varchar(64) NOT NULL COMMENT '步骤类型: face_mask | image_face_mask | implementation_retry | storyboard_first_frame_grid_split',
  `target` text DEFAULT NULL COMMENT '步骤目标（如对应的 video_path）',
  `step_order` int NOT NULL DEFAULT 0 COMMENT '同阶段内执行顺序（0 起始）',
  `status` tinyint NOT NULL DEFAULT 0 COMMENT '0=pending, 1=processing, 2=completed, -1=failed, -2=timeout',
  `params` json DEFAULT NULL COMMENT '步骤参数（JSON 格式）',
  `result_data` json DEFAULT NULL COMMENT '步骤结果数据（JSON 格式）',
  `result_url` text DEFAULT NULL COMMENT '结果文件路径（本地路径或远程 URL）',
  `error_message` text COMMENT '错误信息',
  `async_task_id` int DEFAULT NULL COMMENT '关联 async_tasks.id',
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `completed_at` datetime DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_ai_tool_stage_status` (`ai_tool_id`, `stage`, `status`),
  KEY `idx_status_updated` (`status`, `updated_at`),
  KEY `idx_async_task_id` (`async_task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI工具流水线步骤表';
"""
