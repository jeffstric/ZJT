# -*- coding: utf-8 -*-
"""Compose Jobs Model - 数字人分段拼接编排任务表。

设计定位：**纯编排器**。每段本身就是一条标准 ai_tools(type=35) + tasks(generate_video)
记录，计费/退费/重试全部复用既有链路；compose_jobs 只做三件事：
持有有序段 id 列表、聚合段状态、产出最终拼接结果。**不碰计费**。

⚠️ 与其他任务表的区别（易混淆，修改前请确认目标表）：
  - tasks: ComfyUI 视频/图片生成轮询队列，task_id 为 int（指向 ai_tools.id）
  - tasks(task_type='compose_job'): 本表的调度行，task_id 指向 compose_jobs.id
  - agent_tasks: Agent 对话任务，task_id 为 UUID 字符串
  - async_tasks: 外部服务异步任务（RunningHub 等），有 implementation 字段
"""
import json
import logging
from typing import Any, Dict, List, Optional

import pymysql

from config.constant import ComposeJobStatus
from .database import execute_query, execute_update, execute_insert

logger = logging.getLogger(__name__)


def _parse_json(value: Any) -> Any:
    """JSON 列/text 列经 pymysql 返回为 str，解析失败时容错返回原值。"""
    if isinstance(value, (dict, list)) or value is None:
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class ComposeJob:
    """拼接编排任务记录"""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.status = kwargs.get('status', ComposeJobStatus.PENDING)
        self.segment_ai_tool_ids = _parse_json(kwargs.get('segment_ai_tool_ids')) or []
        self.params = _parse_json(kwargs.get('params')) or {}
        self.result_url = kwargs.get('result_url')
        self.media_mapping_id = kwargs.get('media_mapping_id')
        self.concat_attempts = kwargs.get('concat_attempts') or 0
        self.message = kwargs.get('message')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')

    @property
    def is_terminal(self) -> bool:
        return self.status in (ComposeJobStatus.COMPLETED, ComposeJobStatus.FAILED)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'id': self.id,
            'user_id': self.user_id,
            'status': self.status,
            'segment_ai_tool_ids': self.segment_ai_tool_ids,
            'params': self.params,
            'result_url': self.result_url,
            'media_mapping_id': self.media_mapping_id,
            'concat_attempts': self.concat_attempts,
            'message': self.message,
            'create_at': self.create_at.isoformat() if hasattr(self.create_at, 'isoformat') else self.create_at,
            'update_at': self.update_at.isoformat() if hasattr(self.update_at, 'isoformat') else self.update_at,
        }


class ComposeJobModel:
    """compose_jobs 表数据库操作"""

    @staticmethod
    def create(user_id: int, segment_ai_tool_ids: List[int],
               params: Optional[Dict[str, Any]] = None) -> int:
        """创建编排任务，返回 compose_jobs.id。

        Args:
            user_id: 用户 ID
            segment_ai_tool_ids: 有序段 ai_tools.id 列表（顺序即拼接顺序）
            params: 编排参数快照（prompt/ratio/max_edge 等）
        """
        sql = """
            INSERT INTO compose_jobs (user_id, status, segment_ai_tool_ids, params)
            VALUES (%s, %s, %s, %s)
        """
        seg_json = json.dumps(list(segment_ai_tool_ids), ensure_ascii=False)
        params_json = json.dumps(params or {}, ensure_ascii=False)
        try:
            record_id = execute_insert(sql, (user_id, ComposeJobStatus.PENDING, seg_json, params_json))
            logger.info(f"Created compose job {record_id}: user={user_id}, segments={len(segment_ai_tool_ids)}")
            return record_id
        except pymysql.MySQLError as e:
            logger.error(f"Failed to create compose job for user {user_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to create compose job for user {user_id} (unexpected): {e}")
            raise

    @staticmethod
    def get_by_id(compose_id: int) -> Optional[ComposeJob]:
        """按主键获取编排任务"""
        sql = "SELECT * FROM compose_jobs WHERE id = %s"
        try:
            row = execute_query(sql, (compose_id,), fetch_one=True)
            return ComposeJob(**row) if row else None
        except pymysql.MySQLError as e:
            logger.error(f"Failed to get compose job {compose_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get compose job {compose_id} (unexpected): {e}")
            raise

    @staticmethod
    def update(compose_id: int, **fields: Any) -> int:
        """更新编排任务字段（白名单；segment_ai_tool_ids/params 自动序列化为 JSON）"""
        allowed = ('status', 'segment_ai_tool_ids', 'params', 'result_url',
                   'media_mapping_id', 'concat_attempts', 'message')
        sets, params = [], []
        for key in allowed:
            if key not in fields:
                continue
            value = fields[key]
            if key in ('segment_ai_tool_ids', 'params') and value is not None \
                    and not isinstance(value, str):
                value = json.dumps(value, ensure_ascii=False)
            sets.append(f"{key} = %s")
            params.append(value)
        if not sets:
            logger.warning(f"No valid fields to update for compose job {compose_id}")
            return 0
        params.append(compose_id)
        sql = f"UPDATE compose_jobs SET {', '.join(sets)} WHERE id = %s"
        try:
            return execute_update(sql, tuple(params))
        except pymysql.MySQLError as e:
            logger.error(f"Failed to update compose job {compose_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to update compose job {compose_id} (unexpected): {e}")
            raise

    @staticmethod
    def update_segment_ids(compose_id: int, segment_ai_tool_ids: List[int]) -> int:
        """整表覆盖有序段 id 列表（补段时按 seg_index 原位替换后回写）"""
        return ComposeJobModel.update(compose_id, segment_ai_tool_ids=segment_ai_tool_ids)

    @staticmethod
    def list_by_user(user_id: int, limit: int = 50) -> List[ComposeJob]:
        """按用户列出编排任务（历史页映射用）"""
        sql = """
            SELECT * FROM compose_jobs
            WHERE user_id = %s
            ORDER BY create_at DESC
            LIMIT %s
        """
        try:
            rows = execute_query(sql, (user_id, limit), fetch_all=True)
            return [ComposeJob(**row) for row in rows] if rows else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to list compose jobs for user {user_id}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to list compose jobs for user {user_id} (unexpected): {e}")
            raise

    @staticmethod
    def list_by_status(status_list: List[int]) -> List[ComposeJob]:
        """按状态列出编排任务（运维/巡检用）"""
        if not status_list:
            return []
        placeholders = ','.join(['%s'] * len(status_list))
        sql = f"""
            SELECT * FROM compose_jobs
            WHERE status IN ({placeholders})
            ORDER BY create_at ASC
        """
        try:
            rows = execute_query(sql, tuple(status_list), fetch_all=True)
            return [ComposeJob(**row) for row in rows] if rows else []
        except pymysql.MySQLError as e:
            logger.error(f"Failed to list compose jobs by status {status_list}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to list compose jobs by status {status_list} (unexpected): {e}")
            raise


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `compose_jobs` (
  `id` int NOT NULL AUTO_INCREMENT,
  `user_id` int NOT NULL COMMENT '用户 ID',
  `status` tinyint NOT NULL DEFAULT 0 COMMENT '0-待拼接 1-拼接中 2-完成 -1-失败',
  `segment_ai_tool_ids` text COMMENT '有序段 ai_tools.id JSON 数组',
  `params` text COMMENT '编排参数快照：prompt/ratio/max_edge 等 JSON',
  `result_url` text COMMENT '拼接后的成片地址',
  `media_mapping_id` int DEFAULT NULL COMMENT 'media_file_mapping.id（CDN）',
  `concat_attempts` tinyint NOT NULL DEFAULT 0 COMMENT '连续拼接失败次数（确定性失败快速熔断）',
  `message` varchar(500) DEFAULT NULL COMMENT '状态说明 / 失败原因',
  `create_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_at` timestamp NULL DEFAULT NULL ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  KEY `idx_user_status_create` (`user_id`,`status`,`create_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='数字人分段拼接编排任务表';
"""
