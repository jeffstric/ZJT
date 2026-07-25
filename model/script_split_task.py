"""
Script split task model - persistent task & lease for incremental script splitting.

见 docs/script/script_parser_incremental_split_design.md。
本表是分段拆分的根任务表，承载分段计划、进度、租约和最终结果。
分段检查点存于 script_split_segment。
"""
from typing import Optional, Dict, Any, List, Tuple
from .database import (
    execute_query,
    execute_update,
    execute_insert,
    transaction,
    execute_update_in_transaction,
)
from config.constant import ScriptSplitConstants
import logging
import json
import os
import socket
import uuid

logger = logging.getLogger(__name__)


def _get_worker_id() -> str:
    """为每次 claim 生成唯一租约令牌，避免旧步骤操作新租约。"""
    suffix = uuid.uuid4().hex[:16]
    prefix = f"{socket.gethostname()}-{os.getpid()}"
    return f"{prefix[:47]}-{suffix}"[:64]


class ScriptSplitTask:
    """ScriptSplitTask entity class."""

    def __init__(self, **kwargs):
        self.id = kwargs.get('id')
        self.user_id = kwargs.get('user_id')
        self.source_type = kwargs.get('source_type')
        self.source_id = kwargs.get('source_id')
        self.source_node_key = kwargs.get('source_node_key')
        # 幂等键：user+source+script_sha256+config → 同任务复用
        self.active_key = kwargs.get('active_key')
        self.script_sha256 = kwargs.get('script_sha256')
        self.script_content = kwargs.get('script_content')
        self.request_config = kwargs.get('request_config')
        self.status = kwargs.get('status') or ScriptSplitConstants.STATUS_QUEUED
        self.phase = kwargs.get('phase')
        self.progress = kwargs.get('progress') or 0
        # 分段计划版本：MAX_TOKENS/截断触发语义再分段时递增，上界 PLAN_MAX_REVISIONS
        self.plan_revision = kwargs.get('plan_revision') or 0
        self.segment_plan_json = kwargs.get('segment_plan_json')
        self.current_segment_index = kwargs.get('current_segment_index')
        self.total_segment_count = kwargs.get('total_segment_count')
        self.completed_segment_count = kwargs.get('completed_segment_count') or 0
        self.accepted_registry_json = kwargs.get('accepted_registry_json')
        self.continuity_state_json = kwargs.get('continuity_state_json')
        self.final_result_json = kwargs.get('final_result_json')
        self.last_error_code = kwargs.get('last_error_code')
        self.last_error_message = kwargs.get('last_error_message')
        self.auth_token = kwargs.get('auth_token')
        self.cancel_requested = bool(kwargs.get('cancel_requested'))
        # 租约：worker_id=hostname-pid-claim_uuid（每次领取唯一）
        self.worker_id = kwargs.get('worker_id')
        self.lease_until = kwargs.get('lease_until')
        self.create_at = kwargs.get('create_at')
        self.update_at = kwargs.get('update_at')
        self.completed_at = kwargs.get('completed_at')

    # ---- JSON 字段便捷访问 ----
    def get_request_config(self) -> Dict[str, Any]:
        return _loads(self.request_config, {})

    def get_segment_plan(self) -> Optional[Dict[str, Any]]:
        return _loads(self.segment_plan_json, None)

    def get_accepted_registry(self) -> Dict[str, Any]:
        return _loads(self.accepted_registry_json, {})

    def get_continuity_state(self) -> Dict[str, Any]:
        return _loads(self.continuity_state_json, {})

    def get_final_result(self) -> Optional[Dict[str, Any]]:
        return _loads(self.final_result_json, None)

    def to_public_status(self) -> Dict[str, Any]:
        """对外轻量状态（轮询用），不含 script_content/auth_token/final_result。

        生成阶段进度与段号按段表实时推导，并对 progress 做只增不减，
        避免 completed 被硬门禁回退后 UI 从 80%+ 掉到 40%。
        """
        progress = int(self.progress or 0)
        completed = int(self.completed_segment_count or 0)
        total = self.total_segment_count
        current = self.current_segment_index

        if (
            self.status == ScriptSplitConstants.STATUS_GENERATING
            and self.id is not None
            and int(total or 0) > 0
        ):
            progress, completed, current = ScriptSplitTaskModel.live_generation_progress_view(
                self.id,
                int(total),
                previous_progress=progress,
                fallback_current=current,
            )

        return {
            'task_id': self.id,
            'status': self.status,
            'phase': self.phase,
            'progress': progress,
            'completed_segments': completed,
            'total_segments': total,
            'current_segment': current,
            'message': _phase_message(
                self.status, self.phase, current, total,
            ),
            'poll_after_ms': ScriptSplitConstants.DEFAULT_POLL_MS,
            # 暴露错误码与可恢复性：让 Agent 能程序化区分 paused 根因（外部依赖 /
            # 内容校验 / 硬门禁 / 鉴权失效），而非只看到通用文案「已暂停」。
            'error_code': self.last_error_code,
            'error_message': self.last_error_message,
            'resumable': self.status in (
                ScriptSplitConstants.STATUS_PAUSED,
                ScriptSplitConstants.STATUS_WAITING_AUTH,
            ),
            'resume_hint': _resume_hint(self.status, self.last_error_code),
        }


def _loads(val, default):
    if val is None:
        return default
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except Exception:
        return default


def _phase_message(status, phase, current_seg, total_seg) -> str:
    if status == ScriptSplitConstants.STATUS_QUEUED:
        return '任务已排队'
    if status == ScriptSplitConstants.STATUS_PLANNING:
        return '正在规划分段'
    if status == ScriptSplitConstants.STATUS_GENERATING:
        if total_seg:
            return f'正在拆分第 {current_seg or 0}/{total_seg} 段'
        return '正在拆分分镜'
    if status == ScriptSplitConstants.STATUS_MERGING:
        return '正在合并分段'
    if status == ScriptSplitConstants.STATUS_VALIDATING:
        return '正在全局校验'
    if status == ScriptSplitConstants.STATUS_PUBLISHING:
        return '正在发布结果'
    if status == ScriptSplitConstants.STATUS_COMPLETED:
        return '拆分完成'
    if status == ScriptSplitConstants.STATUS_PAUSED:
        return '任务已暂停，可点击继续'
    if status == ScriptSplitConstants.STATUS_WAITING_AUTH:
        return '鉴权失效，请刷新页面后继续'
    if status == ScriptSplitConstants.STATUS_CANCELLING:
        return '正在取消'
    if status == ScriptSplitConstants.STATUS_CANCELLED:
        return '任务已取消'
    if status == ScriptSplitConstants.STATUS_FAILED:
        return '任务失败'
    return status or ''


def _resume_hint(status: Optional[str], error_code: Optional[str]) -> Optional[str]:
    """针对 paused/waiting_auth 给 Agent/调用方的可读恢复指引。

    返回 None 表示非可恢复状态（无需指引）。指引文案面向程序化消费（Agent），
    与面向前端的 ``_phase_message`` 区分：后者是按钮文案，前者是动作建议。
    """
    if status not in (
        ScriptSplitConstants.STATUS_PAUSED,
        ScriptSplitConstants.STATUS_WAITING_AUTH,
    ):
        return None
    if error_code in ScriptSplitConstants.RESUME_BLOCKED_ERROR_CODES:
        if error_code == "plan_call_failed":
            return "llm_gateway_error: LLM 网关拒绝调用(如 403/5xx)，排查 api key/欠费/网络后调 resume(force=true) 重试"
        if error_code == "plan_timeout":
            return "llm_timeout: LLM 调用超时，排查模型可用性/网络后调 resume(force=true) 重试"
        if error_code == "step_watchdog_timeout":
            return "worker_timeout: 单步超时，排查 worker 进程/LLM 响应后调 resume(force=true) 重试"
        if error_code == "quality_merge_invalid":
            return "quality_merge: 合并阶段实体身份冲突，根治后正常不触发；若仍出现说明规划真源异常，需排查后调 resume(force=true) 重试"
        # 硬门禁类（new_root_location_forbidden / location_parent_*）
        return "hard_gate: 剧本含未建模的顶层场景或父级关系非法，需先在剧本创作页补齐场景资产后调 resume(force=true)"
    if error_code in ScriptSplitConstants.RESUME_NEEDS_AUTH_ERROR_CODES:
        return "auth_expired: 鉴权 token 已失效，先 POST /api/agent-auth/exchange 换取新 auth_token，再带 Authorization 头调 resume"
    # plan_failed / segment_qc_failed / segment_max_retries / segment_repeatedly_interrupted 等
    # 内容校验类：根因与外部依赖无关，直接 resume 即可重试
    return "content_validation: 规划/段内容校验未通过，可直接调 resume 重试"


class ScriptSplitTaskModel:
    """ScriptSplitTask database operations."""

    @staticmethod
    def _row_to_entity(row: Optional[Dict]) -> Optional[ScriptSplitTask]:
        if not row:
            return None
        return ScriptSplitTask(**row)

    @staticmethod
    def get_by_id(task_id: int) -> Optional[ScriptSplitTask]:
        rows = execute_query(
            "SELECT * FROM script_split_task WHERE id = %s",
            (task_id,),
            fetch_one=True,
        )
        return ScriptSplitTaskModel._row_to_entity(rows)

    @staticmethod
    def get_active_by_key(active_key: str) -> Optional[ScriptSplitTask]:
        """按幂等键查找活跃任务（active_key 非 NULL 时唯一）。"""
        rows = execute_query(
            "SELECT * FROM script_split_task WHERE active_key = %s",
            (active_key,),
            fetch_one=True,
        )
        return ScriptSplitTaskModel._row_to_entity(rows)

    @staticmethod
    def get_active_by_source(
        source_type: str, source_id: int, source_node_key: Optional[str] = None
    ) -> Optional[ScriptSplitTask]:
        """按来源查找最近一个活跃任务，供页面刷新恢复。"""
        if source_node_key:
            sql = (
                "SELECT * FROM script_split_task "
                "WHERE source_type = %s AND source_id = %s AND source_node_key = %s "
                "AND status IN (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ORDER BY id DESC LIMIT 1"
            )
            params = (
                source_type, source_id, source_node_key,
                ScriptSplitConstants.STATUS_QUEUED,
                ScriptSplitConstants.STATUS_PLANNING,
                ScriptSplitConstants.STATUS_GENERATING,
                ScriptSplitConstants.STATUS_MERGING,
                ScriptSplitConstants.STATUS_VALIDATING,
                ScriptSplitConstants.STATUS_PUBLISHING,
                ScriptSplitConstants.STATUS_PAUSED,
                ScriptSplitConstants.STATUS_WAITING_AUTH,
                ScriptSplitConstants.STATUS_CANCELLING,
            )
        else:
            sql = (
                "SELECT * FROM script_split_task "
                "WHERE source_type = %s AND source_id = %s "
                "AND status IN (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "ORDER BY id DESC LIMIT 1"
            )
            params = (
                source_type, source_id,
                ScriptSplitConstants.STATUS_QUEUED,
                ScriptSplitConstants.STATUS_PLANNING,
                ScriptSplitConstants.STATUS_GENERATING,
                ScriptSplitConstants.STATUS_MERGING,
                ScriptSplitConstants.STATUS_VALIDATING,
                ScriptSplitConstants.STATUS_PUBLISHING,
                ScriptSplitConstants.STATUS_PAUSED,
                ScriptSplitConstants.STATUS_WAITING_AUTH,
                ScriptSplitConstants.STATUS_CANCELLING,
            )
        rows = execute_query(sql, params, fetch_one=True)
        return ScriptSplitTaskModel._row_to_entity(rows)

    @staticmethod
    def create_or_get_active(
        user_id: int,
        source_type: str,
        source_id: int,
        source_node_key: Optional[str],
        active_key: str,
        script_sha256: str,
        script_content: str,
        request_config: Dict[str, Any],
        auth_token: Optional[str] = None,
    ) -> tuple:
        """幂等创建任务。并发冲突时回查已有活跃任务。

        Returns:
            (task_id, is_new): task_id 为已有或新建的任务 id；is_new 表示是否本次新建。
        """
        config_str = json.dumps(request_config, ensure_ascii=False)
        # INSERT IGNORE + rowcount 区分新建/已存在：
        #   rowcount == 1 → 新建；rowcount == 0 → active_key 冲突（已有活跃任务）。
        # 不能用 ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id) 再靠比较字段判断 is_new，
        # 因为 active_key 本身就是按 (user+source+sha256+config) 算的，冲突时字段必然相同，
        # 会把冲突误判为新建。
        sql = """
            INSERT IGNORE INTO script_split_task
            (user_id, source_type, source_id, source_node_key, active_key,
             script_sha256, script_content, request_config, auth_token, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            user_id, source_type, source_id, source_node_key, active_key,
            script_sha256, script_content, config_str, auth_token,
            ScriptSplitConstants.STATUS_QUEUED,
        )
        try:
            with transaction() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                is_new = cursor.rowcount == 1
                new_id = cursor.lastrowid
            if is_new:
                # 新建成功
                return new_id, True
            # 冲突：回查已有活跃任务。
            # INSERT IGNORE 在唯一键冲突时不插入，而行一定已提交（MySQL 唯一约束
            # 串行化：第二个 INSERT 必然在第一个提交后才能判定冲突），所以这里能查到。
            existing = ScriptSplitTaskModel.get_active_by_key(active_key)
            if existing:
                return existing.id, False
            # 极端竞态下查不到：抛错进入下面的 except 兜底
            raise RuntimeError("active_key 冲突但无法回查到活跃任务，请重试")
        except Exception as e:
            logger.warning("create_or_get_active insert failed, fallback to lookup: %s", e)
            task = ScriptSplitTaskModel.get_active_by_key(active_key)
            if task:
                return task.id, False
            raise

    @staticmethod
    def update_status(
        task_id: int,
        status: str,
        phase: Optional[str] = None,
        progress: Optional[int] = None,
        last_error_code: Optional[str] = None,
        last_error_message: Optional[str] = None,
        clear_error: bool = False,
    ) -> None:
        sets = ["status = %s"]
        params: list = [status]
        if phase is not None:
            sets.append("phase = %s")
            params.append(phase)
        if progress is not None:
            sets.append("progress = %s")
            params.append(progress)
        if last_error_code is not None:
            sets.append("last_error_code = %s")
            params.append(last_error_code)
        if last_error_message is not None:
            sets.append("last_error_message = %s")
            params.append(last_error_message)
        if clear_error:
            sets.append("last_error_code = NULL")
            sets.append("last_error_message = NULL")
        # 进入终态时释放 active_key 和租约，记录完成时间
        if status in ScriptSplitConstants.TERMINAL_STATUSES:
            sets.append("active_key = NULL")
            sets.append("worker_id = NULL")
            sets.append("lease_until = NULL")
            sets.append("completed_at = CURRENT_TIMESTAMP")
        params.append(task_id)
        execute_update(
            f"UPDATE script_split_task SET {', '.join(sets)} WHERE id = %s",
            tuple(params),
        )

    @staticmethod
    def update_plan(task_id: int, plan: Dict[str, Any], plan_revision: int,
                    total_segment_count: int) -> None:
        execute_update(
            "UPDATE script_split_task SET segment_plan_json = %s, plan_revision = %s, "
            "total_segment_count = %s, current_segment_index = %s, "
            "completed_segment_count = 0 WHERE id = %s",
            (json.dumps(plan, ensure_ascii=False), plan_revision,
             total_segment_count, 1 if total_segment_count > 0 else None, task_id),
        )

    @staticmethod
    def save_field(task_id: int, **fields) -> None:
        """通用字段更新，仅更新非 None 字段。值自动 JSON 序列化 dict/list。"""
        if not fields:
            return
        sets = []
        params = []
        for k, v in fields.items():
            if v is None:
                continue
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            sets.append(f"{k} = %s")
            params.append(v)
        if not sets:
            return
        params.append(task_id)
        execute_update(
            f"UPDATE script_split_task SET {', '.join(sets)} WHERE id = %s",
            tuple(params),
        )

    @staticmethod
    def clear_final_result(task_id: int) -> None:
        """发布硬门禁回退到分段修复时清除不可再发布的合并结果。"""
        execute_update(
            "UPDATE script_split_task SET final_result_json = NULL WHERE id = %s",
            (task_id,),
        )

    @staticmethod
    def increment_completed(task_id: int) -> None:
        execute_update(
            "UPDATE script_split_task SET completed_segment_count = completed_segment_count + 1 "
            "WHERE id = %s",
            (task_id,),
        )

    @staticmethod
    def count_completed_segments(task_id: int) -> int:
        """段表实时 completed 计数（生成进度真源）。"""
        from model.script_split_segment import (
            ScriptSplitSegmentModel,
            SEGMENT_STATUS_COMPLETED,
        )
        return int(
            ScriptSplitSegmentModel.count_by_status(
                task_id, SEGMENT_STATUS_COMPLETED,
            ) or 0
        )

    @staticmethod
    def compute_generation_progress(
        task_id: int,
        total_segments: int,
        previous_progress: Optional[int] = None,
        *,
        base: int = 10,
        span: int = 75,
        cap: int = 84,
    ) -> Tuple[int, int]:
        """按段表 completed/total 计算生成阶段进度，且相对 previous 只增不减。

        返回 (progress, completed_count)。
        公式：progress = base + int(span * completed / total)，上限 cap；
        若提供 previous_progress，则 progress = max(previous, 计算值)。
        """
        total = max(1, int(total_segments or 1))
        completed = ScriptSplitTaskModel.count_completed_segments(task_id)
        raw = base + int(span * completed / total)
        raw = min(max(0, raw), cap)
        if previous_progress is not None:
            raw = max(int(previous_progress or 0), raw)
        return raw, completed

    @staticmethod
    def live_generation_progress_view(
        task_id: int,
        total_segments: int,
        previous_progress: Optional[int] = None,
        fallback_current: Optional[int] = None,
    ) -> Tuple[int, int, int]:
        """轮询视图：进度(只增不减) + 实时 completed + 当前未完成段序号。"""
        from model.script_split_segment import ScriptSplitSegmentModel

        progress, completed = ScriptSplitTaskModel.compute_generation_progress(
            task_id,
            total_segments,
            previous_progress=previous_progress,
        )
        total = max(1, int(total_segments or 1))
        first = ScriptSplitSegmentModel.get_first_uncompleted(task_id)
        if first is not None:
            current = int(first.segment_index)
        elif completed >= total:
            current = total
        else:
            current = int(fallback_current or 0) or total
        return progress, completed, current

    @staticmethod
    def sync_generation_progress(
        task_id: int,
        total_segments: int,
        previous_progress: Optional[int] = None,
        *,
        current_segment_index: Optional[int] = None,
    ) -> Tuple[int, int]:
        """写回 completed_segment_count 与单调 progress；返回 (progress, completed)。"""
        progress, completed = ScriptSplitTaskModel.compute_generation_progress(
            task_id,
            total_segments,
            previous_progress=previous_progress,
        )
        fields: Dict[str, Any] = {
            "completed_segment_count": completed,
        }
        if current_segment_index is not None:
            fields["current_segment_index"] = current_segment_index
        ScriptSplitTaskModel.save_field(task_id, **fields)
        ScriptSplitTaskModel.update_status(
            task_id,
            ScriptSplitConstants.STATUS_GENERATING,
            phase="segment_generation",
            progress=progress,
        )
        return progress, completed

    @staticmethod
    def request_cancel(task_id: int) -> None:
        """协作式取消：只置标记，不强杀线程。"""
        execute_update(
            "UPDATE script_split_task SET cancel_requested = 1 WHERE id = %s",
            (task_id,),
        )

    @staticmethod
    def is_cancel_requested(task_id: int) -> bool:
        rows = execute_query(
            "SELECT cancel_requested FROM script_split_task WHERE id = %s",
            (task_id,),
            fetch_one=True,
        )
        return bool(rows and rows.get('cancel_requested'))

    @staticmethod
    def claim_next_task(lease_seconds: int) -> Optional[ScriptSplitTask]:
        """原子领取一个可执行任务，写入 worker_id/lease_until。

        复用 download_queue.claim_pending 模式（事务 + FOR UPDATE）。
        可领取的任务：queued 或可恢复活跃态，并且租约已过期或未持有
        （lease_until IS NULL OR < NOW()）。所有状态统一受租约条件约束。
          ⚠️ 必须显式处理 lease_until IS NULL：MySQL 中 NULL < NOW() 求值为 NULL（falsy），
          若只写 lease_until < NOW()，租约已被 release_lease 置 NULL 的任务永远无法被回收。
        终态、paused、waiting_auth 不被自动领取。
        每次 tick 最多领取一个任务，配合单步推进避免长占用。
        """
        worker_id = _get_worker_id()
        claimable = (
            ScriptSplitConstants.STATUS_QUEUED,
            ScriptSplitConstants.STATUS_PLANNING,
            ScriptSplitConstants.STATUS_GENERATING,
            ScriptSplitConstants.STATUS_MERGING,
            ScriptSplitConstants.STATUS_VALIDATING,
            ScriptSplitConstants.STATUS_PUBLISHING,
            ScriptSplitConstants.STATUS_CANCELLING,
        )
        placeholders = ",".join(["%s"] * len(claimable))
        # 多 worker 分片：仅当 WORKER_TOTAL>0 时追加 id MOD N = index 过滤，
        # 让多个独立 worker 进程各 claim 互不重叠的子集（主调度器不分片，走原逻辑）。
        # ⚠️ 与 FOR UPDATE 配合安全：行级锁保证同一行不会被两个事务同时领走，
        #    分片从源头缩小每个 worker 的扫描范围，进一步降低竞争。
        shard_total = ScriptSplitConstants.WORKER_TOTAL
        shard_clause = ""
        select_params = list(claimable)
        if shard_total and shard_total > 0:
            shard_clause = " AND id MOD %s = %s"
            select_params.extend([shard_total, ScriptSplitConstants.WORKER_INDEX])
        select_sql = f"""
            SELECT id FROM script_split_task
            WHERE status IN ({placeholders})
              AND (lease_until IS NULL OR lease_until < NOW())
            {shard_clause}
            ORDER BY id ASC
            LIMIT 1
            FOR UPDATE
        """
        update_sql = (
            "UPDATE script_split_task "
            "SET worker_id = %s, lease_until = DATE_ADD(NOW(), INTERVAL %s SECOND), "
            "update_at = NOW() WHERE id = %s"
        )
        with transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(select_sql, tuple(select_params))
            rows = cursor.fetchall()
            if not rows:
                return None
            task_id = rows[0][0] if isinstance(rows[0], (tuple, list)) else rows[0]['id']
            cursor.execute(update_sql, (worker_id, lease_seconds, task_id))
        return ScriptSplitTaskModel.get_by_id(task_id)

    @staticmethod
    def release_lease(task_id: int, worker_id: str) -> bool:
        """仅当前 claim 持有者可以释放租约。"""
        affected = execute_update(
            "UPDATE script_split_task SET worker_id = NULL, lease_until = NULL "
            "WHERE id = %s AND worker_id = %s",
            (task_id, worker_id),
        )
        return int(affected or 0) == 1

    @staticmethod
    def renew_lease(task_id: int, worker_id: str, lease_seconds: int) -> bool:
        """仅当前 claim 持有者可以续租；False 表示租约已经丢失。"""
        affected = execute_update(
            "UPDATE script_split_task SET lease_until = DATE_ADD(NOW(), INTERVAL %s SECOND) "
            "WHERE id = %s AND worker_id = %s",
            (lease_seconds, task_id, worker_id),
        )
        return int(affected or 0) == 1


# ==================== CREATE_TABLE_SQL ====================
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `script_split_task` (
    `id` INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    `user_id` INT UNSIGNED NOT NULL COMMENT '创建人',
    `source_type` VARCHAR(32) NOT NULL COMMENT '来源 video_workflow/storyboard/cli',
    `source_id` INT UNSIGNED DEFAULT NULL COMMENT '来源 id（workflow id / storyboard id）',
    `source_node_key` VARCHAR(128) DEFAULT NULL COMMENT '视频工作流节点 key（恢复用）',
    `active_key` VARCHAR(128) DEFAULT NULL COMMENT '幂等键(user+source+sha256+config)；终态置 NULL',
    `script_sha256` VARCHAR(64) NOT NULL COMMENT '剧本内容 sha256',
    `script_content` MEDIUMTEXT NOT NULL COMMENT '原始剧本全文',
    `request_config` JSON DEFAULT NULL COMMENT '拆分请求参数(model/language/world_id 等)',
    `status` VARCHAR(32) NOT NULL DEFAULT 'queued' COMMENT '任务状态，见 ScriptSplitConstants',
    `phase` VARCHAR(64) DEFAULT NULL COMMENT '当前阶段细分（segment_generation 等）',
    `progress` TINYINT UNSIGNED NOT NULL DEFAULT 0 COMMENT '进度 0-100',
    `plan_revision` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '语义再分段版本，上界 PLAN_MAX_REVISIONS',
    `segment_plan_json` JSON DEFAULT NULL COMMENT '阶段一分段计划(锚点+segments)',
    `current_segment_index` INT UNSIGNED DEFAULT NULL COMMENT '当前处理段序号(1-based)',
    `total_segment_count` INT UNSIGNED DEFAULT NULL COMMENT '总段数',
    `completed_segment_count` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '已完成段数',
    `accepted_registry_json` JSON DEFAULT NULL COMMENT '已接受的全局资产注册表(characters/locations/props/spatial_world)',
    `continuity_state_json` JSON DEFAULT NULL COMMENT '上一段结束时的空间连续性状态',
    `final_result_json` JSON DEFAULT NULL COMMENT '合并后的最终 parsed_data',
    `last_error_code` VARCHAR(64) DEFAULT NULL COMMENT '最近错误码',
    `last_error_message` TEXT DEFAULT NULL COMMENT '最近错误信息',
    `auth_token` VARCHAR(512) DEFAULT NULL COMMENT '用户 token(记费用)，不输出到日志/响应',
    `cancel_requested` TINYINT(1) NOT NULL DEFAULT 0 COMMENT '协作式取消标记',
    `worker_id` VARCHAR(64) DEFAULT NULL COMMENT '每次领取唯一令牌(hostname-pid-claim_uuid)',
    `lease_until` DATETIME DEFAULT NULL COMMENT '租约到期时间，过期可被回收',
    `create_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `update_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    `completed_at` DATETIME DEFAULT NULL COMMENT '进入终态时间',
    UNIQUE KEY `uk_script_split_active_key` (`active_key`),
    INDEX `idx_script_split_user` (`user_id`),
    INDEX `idx_script_split_source` (`source_type`, `source_id`),
    INDEX `idx_script_split_status_lease` (`status`, `lease_until`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='剧本分段拆分根任务表';
"""

__all__ = [
    "ScriptSplitTask",
    "ScriptSplitTaskModel",
    "CREATE_TABLE_SQL",
]
