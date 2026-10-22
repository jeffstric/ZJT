# -*- coding: utf-8 -*-
"""Script Extract Task Model - 剧本提取任务表（video_workflow 剧本提取节点）。

跨进程共享的任务状态表：gunicorn 多 worker 部署下，任务创建（POST）与状态
轮询（GET）可能落到不同进程，内存注册表会导致「任务不存在或已过期」404；
落库后任意 worker 均可查询状态，服务重启亦不再丢失已完成/失败的结果。

⚠️ 与其他任务表的区别（易混淆，修改前请确认目标表）：
  - tasks: ComfyUI 视频/图片生成轮询队列，task_id 为 int（指向 ai_tools.id）
  - agent_tasks: Agent 对话任务，task_id 为 UUID 字符串
  - async_tasks: 外部服务异步任务（RunningHub 等），有 implementation 字段
  - script_extract_task: 本表，视频→剧本提取（纯 LLM pipeline，单进程内执行，
    状态跨进程共享；执行进程失联由 updated_at 超时判定）
"""
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pymysql

from .database import execute_query, execute_update, execute_insert

logger = logging.getLogger(__name__)


def _parse_json(value: Any) -> Any:
    """JSON 列经 pymysql 返回为 str，解析失败时容错返回原值。"""
    if isinstance(value, (dict, list)) or value is None:
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class ScriptExtractTask:
    """剧本提取任务记录"""

    def __init__(self, **kwargs):
        self.task_id = kwargs.get('task_id')
        self.user_id = kwargs.get('user_id')
        self.status = kwargs.get('status', 'running')
        self.stage = kwargs.get('stage', 'frames')
        self.progress = _parse_json(kwargs.get('progress')) or {}
        self.error = kwargs.get('error')
        self.result = _parse_json(kwargs.get('result'))
        self.created_at = kwargs.get('created_at')
        self.updated_at = kwargs.get('updated_at')

    def is_expired(self, ttl_seconds: int) -> bool:
        """running 任务超过 ttl 未更新（执行进程失联/重启），视为已过期。"""
        if self.status != 'running' or self.updated_at is None:
            return False
        updated = self.updated_at
        if isinstance(updated, str):
            try:
                updated = datetime.strptime(updated, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                return False
        return (datetime.now() - updated).total_seconds() > ttl_seconds


class ScriptExtractTaskModel:
    """剧本提取任务数据库操作（同步接口；异步上下文调用方需自行 to_thread 包装）"""

    @staticmethod
    def create(task_id: str, user_id: int, stage: str) -> int:
        """创建任务记录"""
        sql = """
            INSERT INTO script_extract_task (task_id, user_id, status, stage, progress)
            VALUES (%s, %s, 'running', %s, '{}')
        """
        try:
            affected = execute_update(sql, (task_id, user_id, stage))
            logger.info(f"Created script extract task: task_id={task_id}, user={user_id}")
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create script extract task {task_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to create script extract task {task_id} (unexpected): {e}")
            raise

    @staticmethod
    def get_by_task_id(task_id: str) -> Optional[ScriptExtractTask]:
        """根据任务 ID 获取任务"""
        sql = "SELECT * FROM script_extract_task WHERE task_id = %s"
        try:
            row = execute_query(sql, (task_id,), fetch_one=True)
            return ScriptExtractTask(**row) if row else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get script extract task {task_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get script extract task {task_id} (unexpected): {e}")
            raise

    @staticmethod
    def update(task_id: str, **fields: Any) -> int:
        """更新任务字段（status/stage/progress/error/result；progress/result 自动序列化为 JSON）"""
        allowed = ('status', 'stage', 'progress', 'error', 'result')
        sets, params = [], []
        for key in allowed:
            if key not in fields:
                continue
            value = fields[key]
            if key in ('progress', 'result') and value is not None and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            sets.append(f"{key} = %s")
            params.append(value)
        if not sets:
            return 0
        params.append(task_id)
        sql = f"UPDATE script_extract_task SET {', '.join(sets)} WHERE task_id = %s"
        try:
            return execute_update(sql, tuple(params))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update script extract task {task_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update script extract task {task_id} (unexpected): {e}")
            raise

    @staticmethod
    def get_running_by_user(user_id: int, stale_seconds: int) -> Optional[ScriptExtractTask]:
        """获取用户当前活跃（未过期）的 running 任务；过期 running 视为失联，不算占用。"""
        sql = """
            SELECT * FROM script_extract_task
            WHERE user_id = %s AND status = 'running'
              AND updated_at >= NOW() - INTERVAL %s SECOND
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            row = execute_query(sql, (user_id, stale_seconds), fetch_one=True)
            return ScriptExtractTask(**row) if row else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get running script extract task for user {user_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get running script extract task for user {user_id} (unexpected): {e}")
            raise

    @staticmethod
    def mark_stale_running_failed(user_id: int, stale_seconds: int, error: str) -> int:
        """把用户超期未更新的 running 任务标记为失败（执行进程失联），释放并发占用。"""
        sql = """
            UPDATE script_extract_task
            SET status = 'failed', stage = 'done', error = %s
            WHERE user_id = %s AND status = 'running'
              AND updated_at < NOW() - INTERVAL %s SECOND
        """
        try:
            affected = execute_update(sql, (error, user_id, stale_seconds))
            if affected:
                logger.warning(
                    f"Marked {affected} stale running script extract task(s) as failed for user {user_id}"
                )
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to mark stale tasks failed for user {user_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to mark stale tasks failed for user {user_id} (unexpected): {e}")
            raise

    @staticmethod
    def cleanup_expired(ttl_seconds: int, limit: int = 500) -> int:
        """惰性清理超过 TTL 的历史记录（含失联 running），防表膨胀。"""
        sql = """
            DELETE FROM script_extract_task
            WHERE updated_at < NOW() - INTERVAL %s SECOND
            ORDER BY updated_at ASC
            LIMIT %s
        """
        try:
            affected = execute_update(sql, (ttl_seconds, limit))
            if affected:
                logger.info(f"Cleaned up {affected} expired script extract task(s)")
            return affected
        except pymysql.MySQLError as e:
            logger.error(f"Failed to cleanup expired script extract tasks: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to cleanup expired script extract tasks (unexpected): {e}")
            raise

    @staticmethod
    def list_recent_by_user(user_id: int, limit: int = 10) -> List[ScriptExtractTask]:
        """获取用户最近任务（运维/排查用）。"""
        sql = """
            SELECT * FROM script_extract_task
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
        """
        try:
            rows = execute_query(sql, (user_id, limit), fetch_all=True)
            return [ScriptExtractTask(**row) for row in rows] if rows else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to list script extract tasks for user {user_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to list script extract tasks for user {user_id} (unexpected): {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `script_extract_task` (
  `task_id` varchar(64) NOT NULL COMMENT '任务ID（uuid hex）',
  `user_id` int NOT NULL COMMENT '用户 ID',
  `status` varchar(20) NOT NULL DEFAULT 'running' COMMENT '任务状态：running/success/failed',
  `stage` varchar(20) NOT NULL DEFAULT 'frames' COMMENT '当前阶段：frames/audio/asr/llm/done',
  `progress` json DEFAULT NULL COMMENT '进度明细（如 ASR 分段完成数）',
  `error` text COMMENT '错误信息',
  `result` json DEFAULT NULL COMMENT '提取结果（剧本 + 元信息）',
  `created_at` datetime DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`task_id`),
  KEY `idx_user_status` (`user_id`, `status`),
  KEY `idx_updated_at` (`updated_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='剧本提取任务表（跨进程共享状态）';
"""
