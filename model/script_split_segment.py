"""
Script split segment model - per-segment checkpoint for incremental script splitting.

见 docs/script/script_parser_incremental_split_design.md。
每个分段一条记录，作为断点续传的检查点。段成功后立即持久化，失败时只重试当前段。
"""
from typing import Optional, Dict, Any, List
from .database import execute_query, execute_update, execute_insert, transaction
from config.constant import ScriptSplitConstants
import logging
import json

logger = logging.getLogger(__name__)


# 分段状态
SEGMENT_STATUS_PENDING = "pending"        # 待处理
SEGMENT_STATUS_GENERATING = "generating"  # 生成中
SEGMENT_STATUS_COMPLETED = "completed"    # 通过校验并持久化
SEGMENT_STATUS_FAILED = "failed"          # 失败（等待重试）


def _loads(val, default):
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


class ScriptSplitSegment:
    """ScriptSplitSegment entity class (单段检查点)."""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.task_id = kwargs.get('task_id')
        self.segment_index = kwargs.get('segment_index')
        self.segment_id = kwargs.get('segment_id')
        self.source_block_ids = kwargs.get('source_block_ids')
        self.source_content = kwargs.get('source_content')
        self.source_sha256 = kwargs.get('source_sha256')
        self.status = kwargs.get('status') or SEGMENT_STATUS_PENDING
        self.attempt_count = kwargs.get('attempt_count') or 0
        self.raw_response = kwargs.get('raw_response')
        self.parsed_result_json = kwargs.get('parsed_result_json')
        self.validation_errors = kwargs.get('validation_errors')
        self.continuity_in_json = kwargs.get('continuity_in_json')
        self.continuity_out_json = kwargs.get('continuity_out_json')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')
        self.completed_at = kwargs.get('completed_at')

    def get_block_ids(self) -> List[str]:
        v = _loads(self.source_block_ids, [])
        return v if isinstance(v, list) else []

    def get_parsed_result(self) -> Optional[Dict[str, Any]]:
        return _loads(self.parsed_result_json, None)

    def get_validation_errors(self) -> List[Dict[str, Any]]:
        v = _loads(self.validation_errors, [])
        return v if isinstance(v, list) else []

    def get_continuity_in(self) -> Dict[str, Any]:
        return _loads(self.continuity_in_json, {})

    def get_continuity_out(self) -> Dict[str, Any]:
        return _loads(self.continuity_out_json, {})


class ScriptSplitSegmentModel:
    """ScriptSplitSegment database operations."""

    @staticmethod
    def _row_to_entity(row: Optional[Dict]) -> Optional[ScriptSplitSegment]:
        if not row:
            return None
        return ScriptSplitSegment(**row)

    @staticmethod
    def upsert(task_id: int, segment_index: int, segment_id: str,
               source_block_ids: List[str], source_content: str,
               source_sha256: str) -> int:
        """插入或更新分段记录（ON DUPLICATE KEY 保留已完成的 parsed_result）。"""
        sql = """
            INSERT INTO script_split_segment
            (task_id, segment_index, segment_id, source_block_ids,
             source_content, source_sha256, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                segment_id = VALUES(segment_id),
                source_block_ids = VALUES(source_block_ids),
                source_content = VALUES(source_content),
                source_sha256 = VALUES(source_sha256)
        """
        params = (
            task_id, segment_index, segment_id,
            json.dumps(source_block_ids, ensure_ascii=False),
            source_content, source_sha256,
            SEGMENT_STATUS_PENDING,
        )
        return execute_insert(sql, params)

    @staticmethod
    def replace_all(task_id: int, segments: List[Dict[str, Any]]) -> None:
        """语义再分段后用新计划替换全部分段记录。

        事务内删除旧分段、插入新分段，保证检查点一致。
        """
        if not segments:
            raise ValueError("segments must not be empty")
        from .database import transaction
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM script_split_segment WHERE task_id = %s",
                (task_id,),
            )
            for seg in segments:
                cursor.execute(
                    """
                    INSERT INTO script_split_segment
                    (task_id, segment_index, segment_id, source_block_ids,
                     source_content, source_sha256, status)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        task_id,
                        seg['segment_index'],
                        seg['segment_id'],
                        json.dumps(seg['source_block_ids'], ensure_ascii=False),
                        seg['source_content'],
                        seg['source_sha256'],
                        SEGMENT_STATUS_PENDING,
                    ),
                )

    @staticmethod
    def get_by_index(task_id: int, segment_index: int) -> Optional[ScriptSplitSegment]:
        rows = execute_query(
            "SELECT * FROM script_split_segment "
            "WHERE task_id = %s AND segment_index = %s",
            (task_id, segment_index),
            fetch_one=True,
        )
        return ScriptSplitSegmentModel._row_to_entity(rows)

    @staticmethod
    def get_all(task_id: int) -> List[ScriptSplitSegment]:
        rows = execute_query(
            "SELECT * FROM script_split_segment WHERE task_id = %s ORDER BY segment_index ASC",
            (task_id,),
            fetch_all=True,
        )
        return [ScriptSplitSegment(**r) for r in (rows or [])]

    @staticmethod
    def get_completed(task_id: int) -> List[ScriptSplitSegment]:
        rows = execute_query(
            "SELECT * FROM script_split_segment "
            "WHERE task_id = %s AND status = %s ORDER BY segment_index ASC",
            (task_id, SEGMENT_STATUS_COMPLETED),
            fetch_all=True,
        )
        return [ScriptSplitSegment(**r) for r in (rows or [])]

    @staticmethod
    def get_first_uncompleted(task_id: int) -> Optional[ScriptSplitSegment]:
        """从第一个未完成段继续（断点续传）。"""
        rows = execute_query(
            "SELECT * FROM script_split_segment "
            "WHERE task_id = %s AND status != %s ORDER BY segment_index ASC LIMIT 1",
            (task_id, SEGMENT_STATUS_COMPLETED),
            fetch_one=True,
        )
        return ScriptSplitSegmentModel._row_to_entity(rows)

    @staticmethod
    def get_uncompleted(task_id: int, limit: int) -> List[ScriptSplitSegment]:
        """按原文顺序取得一批未完成段，供效果模式并发处理。"""
        safe_limit = max(1, int(limit))
        rows = execute_query(
            "SELECT * FROM script_split_segment "
            "WHERE task_id = %s AND status != %s "
            f"ORDER BY segment_index ASC LIMIT {safe_limit}",
            (task_id, SEGMENT_STATUS_COMPLETED),
            fetch_all=True,
        )
        return [ScriptSplitSegment(**row) for row in (rows or [])]

    @staticmethod
    def save_success(task_id: int, segment_index: int,
                     parsed_result: Dict[str, Any],
                     continuity_out: Dict[str, Any],
                     raw_response: Optional[str] = None,
                     continuity_in: Optional[Dict[str, Any]] = None,
                     validation_errors: Optional[List[Dict[str, Any]]] = None) -> None:
        """保存已完成段；强制接纳时可保留最后一轮质检问题。"""
        fields = {
            'status': SEGMENT_STATUS_COMPLETED,
            'parsed_result_json': json.dumps(parsed_result, ensure_ascii=False),
            'continuity_out_json': json.dumps(continuity_out, ensure_ascii=False),
            'validation_errors': (
                json.dumps(validation_errors, ensure_ascii=False)
                if validation_errors else None
            ),
        }
        if raw_response is not None:
            fields['raw_response'] = raw_response
        if continuity_in is not None:
            fields['continuity_in_json'] = json.dumps(continuity_in, ensure_ascii=False)
        sets = []
        params = []
        for k, v in fields.items():
            sets.append(f"{k} = %s")
            params.append(v)
        # completed_at 使用 SQL 函数，不能作为字符串参数传入
        sets.append("completed_at = NOW()")
        params.append(task_id)
        params.append(segment_index)
        execute_update(
            f"UPDATE script_split_segment SET {', '.join(sets)} "
            "WHERE task_id = %s AND segment_index = %s",
            tuple(params),
        )

    @staticmethod
    def save_failure(task_id: int, segment_index: int,
                     errors: List[Dict[str, Any]],
                     raw_response: Optional[str] = None,
                     parsed_result: Optional[Dict[str, Any]] = None) -> None:
        """段失败后记录错误和尝试次数；完整候选可供下一 tick 定向修复。"""
        sets = [
            "status = %s",
            "validation_errors = %s",
            "attempt_count = attempt_count + 1",
        ]
        params: list = [
            SEGMENT_STATUS_FAILED,
            json.dumps(errors, ensure_ascii=False),
        ]
        if raw_response is not None:
            sets.append("raw_response = %s")
            params.append(raw_response)
        if parsed_result is not None:
            sets.append("parsed_result_json = %s")
            params.append(json.dumps(parsed_result, ensure_ascii=False))
        params.append(task_id)
        params.append(segment_index)
        execute_update(
            f"UPDATE script_split_segment SET {', '.join(sets)} "
            "WHERE task_id = %s AND segment_index = %s",
            tuple(params),
        )

    @staticmethod
    def reopen_completed_for_hard_errors(
        task_id: int,
        errors_by_segment: Dict[int, List[Dict[str, Any]]],
    ) -> int:
        """原子重开合并级硬门禁命中的历史完成段，并校准根任务计数。"""
        if not errors_by_segment:
            return ScriptSplitSegmentModel.count_by_status(
                task_id, SEGMENT_STATUS_COMPLETED,
            )

        from .database import transaction

        affected_indexes = sorted(int(index) for index in errors_by_segment)
        with transaction() as conn:
            cursor = conn.cursor()
            for segment_index in affected_indexes:
                cursor.execute(
                    "SELECT validation_errors FROM script_split_segment "
                    "WHERE task_id = %s AND segment_index = %s FOR UPDATE",
                    (task_id, segment_index),
                )
                row = cursor.fetchone() or {}
                prior_errors = _loads(row.get("validation_errors"), [])
                retained_diagnostics = [
                    error for error in prior_errors
                    if isinstance(error, dict)
                    and error.get("_forced_accept")
                    and not error.get("_hard_gate")
                ]
                hard_errors = [
                    dict(error, _hard_gate=True)
                    for error in (errors_by_segment.get(segment_index) or [])
                ]
                cursor.execute(
                    "UPDATE script_split_segment SET status = %s, "
                    "validation_errors = %s, completed_at = NULL "
                    "WHERE task_id = %s AND segment_index = %s",
                    (
                        SEGMENT_STATUS_FAILED,
                        json.dumps(retained_diagnostics + hard_errors, ensure_ascii=False),
                        task_id,
                        segment_index,
                    ),
                )

            cursor.execute(
                "SELECT COUNT(*) AS cnt FROM script_split_segment "
                "WHERE task_id = %s AND status = %s",
                (task_id, SEGMENT_STATUS_COMPLETED),
            )
            count_row = cursor.fetchone() or {}
            completed_count = int(count_row.get("cnt") or 0)
            cursor.execute(
                "UPDATE script_split_task SET completed_segment_count = %s, "
                "current_segment_index = %s, phase = %s "
                "WHERE id = %s",
                (
                    completed_count,
                    affected_indexes[0],
                    "segment_generation",
                    task_id,
                ),
            )
        return completed_count

    @staticmethod
    def mark_generating(task_id: int, segment_index: int) -> None:
        execute_update(
            "UPDATE script_split_segment SET status = %s "
            "WHERE task_id = %s AND segment_index = %s",
            (SEGMENT_STATUS_GENERATING, task_id, segment_index),
        )

    @staticmethod
    def reclaim_stale_generating(
        task_id: int,
        worker_id: str,
        max_recoveries: int,
    ) -> Dict[str, Any]:
        """在当前任务租约保护下回收崩溃遗留的 generating 段。

        调用方不能只依赖进程内判断；本方法在同一事务中锁定根任务并验证
        owner + lease，再锁定并更新段检查点。attempt_count 不在这里增加。
        """
        result = {
            "lease_owned": False,
            "reclaimed_count": 0,
            "exhausted_segment_indexes": [],
        }
        safe_limit = max(1, int(max_recoveries))
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM script_split_task "
                "WHERE id = %s AND worker_id = %s AND lease_until >= NOW() FOR UPDATE",
                (task_id, worker_id),
            )
            if not cursor.fetchone():
                return result
            result["lease_owned"] = True

            cursor.execute(
                "SELECT segment_index, validation_errors "
                "FROM script_split_segment "
                "WHERE task_id = %s AND status = %s "
                "ORDER BY segment_index ASC FOR UPDATE",
                (task_id, SEGMENT_STATUS_GENERATING),
            )
            rows = cursor.fetchall() or []
            for row in rows:
                segment_index = int(
                    row.get("segment_index")
                    if isinstance(row, dict) else row[0]
                )
                raw_errors = (
                    row.get("validation_errors")
                    if isinstance(row, dict) else row[1]
                )
                errors = _loads(raw_errors, [])
                if not isinstance(errors, list):
                    errors = []
                prior_count = max(
                    [
                        int(error.get("_stale_recovery_count", 0) or 0)
                        for error in errors
                        if isinstance(error, dict)
                    ] or [0]
                )
                recovery_count = prior_count + 1
                errors = [
                    error for error in errors
                    if not (
                        isinstance(error, dict)
                        and error.get("code") in {
                            "segment_interrupted",
                            "segment_repeatedly_interrupted",
                        }
                    )
                ]
                exhausted = recovery_count >= safe_limit
                errors.append({
                    "code": (
                        "segment_repeatedly_interrupted"
                        if exhausted else "segment_interrupted"
                    ),
                    "severity": "error" if exhausted else "warning",
                    "message": (
                        f"段 {segment_index} 连续 {recovery_count} 次在生成中被中断，已暂停等待人工继续"
                        if exhausted else
                        f"段 {segment_index} 上一次生成被中断，已自动回收重试"
                    ),
                    "_stale_recovery_count": recovery_count,
                    "_qc_round": 0,
                    "_call_failure_count": 0,
                })
                cursor.execute(
                    "UPDATE script_split_segment "
                    "SET status = %s, validation_errors = %s, update_at = NOW() "
                    "WHERE task_id = %s AND segment_index = %s AND status = %s",
                    (
                        SEGMENT_STATUS_FAILED,
                        json.dumps(errors, ensure_ascii=False),
                        task_id,
                        segment_index,
                        SEGMENT_STATUS_GENERATING,
                    ),
                )
                result["reclaimed_count"] += 1
                if exhausted:
                    result["exhausted_segment_indexes"].append(segment_index)
        return result

    @staticmethod
    def reset_retry_budget(task_id: int) -> None:
        """为用户主动恢复的当前未完成段开启新的重试周期。

        保留最近一次完整候选和业务反馈，只重置反馈中的内部周期计数。
        attempt_count 继续作为全生命周期诊断统计，不在恢复时归零。
        状态写回 pending，确保效果模式依赖调度会再次选中该段（见 §8.1）。
        """
        segment = ScriptSplitSegmentModel.get_first_uncompleted(task_id)
        if segment is None:
            return
        errors = []
        for error in segment.get_validation_errors():
            if not isinstance(error, dict):
                continue
            reset_error = dict(error)
            reset_error["_qc_round"] = 0
            reset_error["_call_failure_count"] = 0
            reset_error["_character_hard_round"] = 0
            reset_error["_stale_recovery_count"] = 0
            errors.append(reset_error)
        execute_update(
            "UPDATE script_split_segment SET status = %s, validation_errors = %s "
            "WHERE task_id = %s AND segment_index = %s",
            (
                SEGMENT_STATUS_PENDING,
                json.dumps(errors, ensure_ascii=False) if errors else None,
                task_id,
                segment.segment_index,
            ),
        )

    @staticmethod
    def count_by_status(task_id: int, status: str) -> int:
        rows = execute_query(
            "SELECT COUNT(*) AS cnt FROM script_split_segment "
            "WHERE task_id = %s AND status = %s",
            (task_id, status),
            fetch_one=True,
        )
        return int(rows['cnt']) if rows else 0

    @staticmethod
    def get_attempt_count(task_id: int, segment_index: int) -> int:
        rows = execute_query(
            "SELECT attempt_count FROM script_split_segment "
            "WHERE task_id = %s AND segment_index = %s",
            (task_id, segment_index),
            fetch_one=True,
        )
        return int(rows['attempt_count']) if rows else 0


# ==================== CREATE_TABLE_SQL ====================
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `script_split_segment` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `task_id` INT UNSIGNED NOT NULL COMMENT '所属根任务 id',
    `segment_index` INT UNSIGNED NOT NULL COMMENT '段序号(1-based)，与原文顺序一致',
    `segment_id` VARCHAR(64) NOT NULL COMMENT '模型规划的 segment_id（如 seg_0003）',
    `source_block_ids` JSON NOT NULL COMMENT '本段覆盖的锚点 block_id 列表',
    `source_content` MEDIUMTEXT NOT NULL COMMENT '本段对应原文（拼接的 block content）',
    `source_sha256` VARCHAR(64) NOT NULL COMMENT '本段原文 sha256',
    `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT 'pending/generating/completed/failed',
    `attempt_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '同边界重试次数（上界 SEGMENT_MAX_RETRIES）',
    `raw_response` LONGTEXT DEFAULT NULL COMMENT '模型原始响应（调试用）',
    `parsed_result_json` JSON DEFAULT NULL COMMENT '通过校验后的段级 parsed_data',
    `validation_errors` JSON DEFAULT NULL COMMENT '失败时的结构化错误列表',
    `continuity_in_json` JSON DEFAULT NULL COMMENT '本段开始时的空间连续性状态',
    `continuity_out_json` JSON DEFAULT NULL COMMENT '本段结束时的空间连续性状态',
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `completed_at` DATETIME DEFAULT NULL COMMENT '段完成时间',
    UNIQUE KEY `uk_script_split_seg_index` (`task_id`, `segment_index`),
    UNIQUE KEY `uk_script_split_seg_id` (`task_id`, `segment_id`),
    INDEX `idx_script_split_seg_status` (`task_id`, `status`),
    FOREIGN KEY (`task_id`) REFERENCES `script_split_task`(`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='剧本分段拆分检查点表';
"""

__all__ = [
    "ScriptSplitSegment",
    "ScriptSplitSegmentModel",
    "CREATE_TABLE_SQL",
    "SEGMENT_STATUS_PENDING",
    "SEGMENT_STATUS_GENERATING",
    "SEGMENT_STATUS_COMPLETED",
    "SEGMENT_STATUS_FAILED",
]
