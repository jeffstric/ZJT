"""
Script split engine - 两阶段编排、上下文构建、合并、局部重试。

见 docs/script/script_parser_incremental_split_design.md §7 §8 §9。
本模块是分段拆分的编排核心，被 task/script_split_task.py（Step 5 worker）调用。
每个方法对应 worker 的一个「单步」，步间释放租约，支持崩溃恢复。

设计要点：
- 阶段一规划只做一次（成功后持久化），MAX_TOKENS 时才局部再规划。
- 阶段二逐段调用 parse_script_to_shots（复用现有提示词/清洗/质检），
  传入 segment_context + strict_json=True + qc_feedback。
- 单段通过校验，或达到 QC 上限后强制接纳合法候选时 commit 检查点。
- 全段完成后合并、全局校验、renumber。
"""
import logging
import asyncio
from typing import Dict, Any, List, Optional, Tuple

from config.constant import ScriptSplitConstants, ScriptSplitQcConstants
from llm.script_split_qc_agent import create_qc_log_context, run_script_split_qc
from services.script_split_planner import (
    anchorize_script,
    validate_segment_plan,
    plan_to_segments,
)
from services.script_split_registry import (
    AcceptedRegistry,
    validate_segment_entities,
    validate_segment_spatial_references,
    renumber_global,
)
from services.script_split_strategy import get_script_split_strategy
from model.script_split_task import ScriptSplitTaskModel, ScriptSplitTask
from model.script_split_segment import (
    ScriptSplitSegmentModel,
    SEGMENT_STATUS_COMPLETED,
)

logger = logging.getLogger(__name__)


class EngineError(Exception):
    """engine 单步执行的业务错误。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


class TaskPaused(EngineError):
    """单段达到重试上限或 plan_revision 上界，进入 paused。"""

    def __init__(self, code: str, message: str):
        super().__init__(code, message)


class CancelledByUser(EngineError):
    """协作式取消生效。"""

    def __init__(self):
        super().__init__("cancelled", "用户已取消任务")


class WaitingAuth(EngineError):
    """鉴权失效，进入 waiting_auth。"""

    def __init__(self, message: str = "鉴权失效，请刷新页面后继续"):
        super().__init__("waiting_auth", message)


def _build_plan_validation_payload(
    task_id: int,
    plan_kind: str,
    attempt: int,
    plan: Optional[Dict[str, Any]],
    finish_reason: Optional[str],
    passed: bool,
    errors: List[Dict[str, Any]],
    log_context=None,
) -> Dict[str, Any]:
    """构造不包含认证信息的规划校验诊断摘要。"""
    plan_data = plan if isinstance(plan, dict) else {}
    segments = plan_data.get("segments")
    if not isinstance(segments, list):
        segments = []
    safe_errors = list(errors or [])
    parse_error = getattr(log_context, "parse_error", None)
    if parse_error:
        safe_errors.insert(0, {
            "code": "plan_json_parse_failed",
            "message": parse_error,
        })
    segment_summaries = []
    for segment in segments:
        if not isinstance(segment, dict):
            continue
        segment_summaries.append({
            "segment_id": segment.get("segment_id"),
            "block_ids": segment.get("block_ids") or [],
        })
    return {
        "task_id": task_id,
        "plan_kind": plan_kind,
        "attempt": attempt,
        "passed": bool(passed),
        "finish_reason": finish_reason,
        "segment_count": len(segment_summaries),
        "errors": safe_errors,
        "segments": segment_summaries,
    }


def _build_plan_call_failure_payload(
    task_id: int,
    plan_kind: str,
    attempt: int,
    error_code: str,
    message: str,
) -> Dict[str, Any]:
    return {
        "task_id": task_id,
        "plan_kind": plan_kind,
        "attempt": attempt,
        "passed": False,
        "finish_reason": None,
        "segment_count": 0,
        "errors": [{"code": error_code, "message": message}],
        "segments": [],
    }


# ---- 单步：阶段一规划 ----

async def step_plan(task: ScriptSplitTask) -> None:
    """执行阶段一语义分段规划（仅在无计划时执行一次）。

    成功后持久化分段计划到 task 和 segment 表。
    失败重试上界 PLAN_MAX_RETRIES；超过则 paused。
    """
    from llm.script_segment_planner import (
        create_plan_log_context,
        plan_segments,
        write_plan_validation_log,
    )

    cfg = task.get_request_config()
    script = task.script_content or ""
    strategy = get_script_split_strategy(cfg.get("sequence_mode", "speed"))

    # 已有计划（断点续传）则跳过规划
    if task.get_segment_plan():
        logger.info("task %s 已有分段计划，跳过规划", task.id)
        return

    anchors = anchorize_script(script)
    if not anchors:
        raise EngineError("empty_script", "剧本为空，无法分段")

    plan = None
    planning_prompt = strategy.build_planning_prompt(
        anchors,
        ScriptSplitConstants.SEGMENT_MAX_OUTPUT_TOKENS,
    )
    last_errors: List[Dict[str, Any]] = []
    for attempt in range(1, ScriptSplitConstants.PLAN_MAX_RETRIES + 1):
        if _is_cancelled(task.id):
            raise CancelledByUser()
        feedback = None
        if last_errors:
            feedback = _format_plan_errors(last_errors)
        log_context = create_plan_log_context(task.id, "initial", attempt)
        try:
            raw_plan, finish_reason = await plan_segments(
                anchors=anchors,
                model=cfg.get("model") or "gemini-3-flash-preview",
                auth_token=task.auth_token,
                vendor_id=cfg.get("vendor_id"),
                model_id=cfg.get("model_id"),
                enable_thinking=cfg.get("enable_thinking", False),
                thinking_effort=cfg.get("thinking_effort", "medium"),
                timeout_seconds=ScriptSplitConstants.LLM_TIMEOUT_SECONDS,
                feedback=feedback,
                log_context=log_context,
                prompt_override=planning_prompt,
            )
        except asyncio.TimeoutError:
            await write_plan_validation_log(
                log_context,
                _build_plan_call_failure_payload(
                    task.id,
                    "initial",
                    attempt,
                    "plan_timeout",
                    "规划模型调用超时",
                ),
            )
            raise EngineError("plan_timeout", "规划模型调用超时")
        except Exception as e:
            msg = str(e)
            await write_plan_validation_log(
                log_context,
                _build_plan_call_failure_payload(
                    task.id,
                    "initial",
                    attempt,
                    "plan_call_failed",
                    "规划模型调用失败",
                ),
            )
            if _is_auth_error(msg):
                raise WaitingAuth()
            raise EngineError("plan_call_failed", msg)

        ok, errors = validate_segment_plan(raw_plan, anchors)
        compiled_plan = raw_plan
        if ok:
            try:
                compiled_plan = strategy.compile_plan(raw_plan, anchors)
            except ValueError as exc:
                ok = False
                errors = [{
                    "code": "quality_plan_invalid",
                    "message": str(exc),
                }]
        await write_plan_validation_log(
            log_context,
            _build_plan_validation_payload(
                task.id,
                "initial",
                attempt,
                raw_plan,
                finish_reason,
                ok,
                errors,
                log_context,
            ),
        )
        if ok:
            plan = compiled_plan
            break
        last_errors = errors
        logger.warning("task %s 规划第 %d 次失败: %s", task.id, attempt, errors)

    if plan is None:
        raise TaskPaused("plan_failed",
                         f"规划失败，已重试 {ScriptSplitConstants.PLAN_MAX_RETRIES} 次")

    # 持久化计划
    segs = plan_to_segments(plan, anchors)
    ScriptSplitTaskModel.update_plan(task.id, plan, plan_revision=0,
                                     total_segment_count=len(segs))
    compiled_registry = plan.get("compiled_registry")
    if isinstance(compiled_registry, dict):
        ScriptSplitTaskModel.save_field(
            task.id,
            accepted_registry_json=compiled_registry,
        )
    # 一次性写入全部 segment 检查点；空计划会在模型层拒绝。
    ScriptSplitSegmentModel.replace_all(task.id, segs)
    ScriptSplitTaskModel.update_status(
        task.id, ScriptSplitConstants.STATUS_GENERATING,
        phase="segment_generation", progress=10,
    )


# ---- 单步：阶段二生成单个段 ----

async def step_generate_segment(
    task: ScriptSplitTask,
    _segment=None,
    _parallel_child: bool = False,
) -> None:
    """生成下一个未完成段（断点续传从第一个未完成段继续）。

    调用失败受 SEGMENT_MAX_RETRIES 保护；质检最多修正 qc_max_rounds 轮，
    耗尽后采用最后一轮合法候选继续。
    """
    from llm.script_parser import parse_script_to_shots
    cfg = task.get_request_config()
    strategy = get_script_split_strategy(cfg.get("sequence_mode", "speed"))
    plan = task.get_segment_plan() or {}
    if strategy.parallel_enabled and not _parallel_child:
        await _step_generate_parallel_batch(task, strategy)
        return

    seg = _segment or ScriptSplitSegmentModel.get_first_uncompleted(task.id)
    if seg is None:
        # 无未完成段时立即验证检查点并合并，避免进入空 merging 循环。
        await step_merge(task)
        return

    if _is_cancelled(task.id):
        raise CancelledByUser()

    registry = _load_registry(task)
    ScriptSplitSegmentModel.mark_generating(task.id, seg.segment_index)
    ScriptSplitTaskModel.save_field(
        task.id, current_segment_index=seg.segment_index,
    )

    # 构建段上下文
    segment_context = _build_segment_context(task, seg, registry)
    if _parallel_child:
        segment_context.update(strategy.build_segment_context(plan, seg.segment_id))
        contract = segment_context.get("spatial_contract") or {}
        segment_context["previous_tail_summary"] = []
        segment_context["continuity_state"] = contract.get("continuity_in") or {}
    total = task.total_segment_count or 1

    last_errors: List[Dict[str, Any]] = []
    last_parsed_result: Optional[Dict[str, Any]] = None
    enable_qc = bool(cfg.get("enable_qc", False))
    try:
        qc_max_rounds = int(
            cfg.get("qc_max_rounds", ScriptSplitQcConstants.DEFAULT_MAX_ROUNDS)
        )
    except (TypeError, ValueError):
        qc_max_rounds = ScriptSplitQcConstants.DEFAULT_MAX_ROUNDS
    qc_max_rounds = max(
        ScriptSplitQcConstants.MIN_MAX_ROUNDS,
        min(ScriptSplitQcConstants.MAX_MAX_ROUNDS, qc_max_rounds),
    )
    # 一个 scheduler tick 最多调用一次 LLM。上一 tick 的完整候选和错误已经
    # 持久化在 segment 中，本 tick 只负责继续一次定向修复，避免多轮调用共享
    # 同一个 360s watchdog 预算。
    attempt_count = int(seg.attempt_count or 0)
    last_errors = seg.get_validation_errors()
    last_parsed_result = seg.get_parsed_result()
    call_failure_count = max(
        [int(e.get("_call_failure_count", 0) or 0) for e in last_errors] or [0]
    )
    qc_rounds = max(
        [int(e.get("_qc_round", 0) or 0) for e in last_errors] or [0]
    )
    # 兼容升级前没有内部计数元数据的失败检查点。显式存在值为 0 的元数据
    # 表示用户已经开启新重试周期，不能再由全生命周期 attempt_count 覆盖。
    has_retry_metadata = any(
        isinstance(error, dict)
        and ("_call_failure_count" in error or "_qc_round" in error)
        for error in last_errors
    )
    if last_errors and not has_retry_metadata:
        last_codes = {e.get("code") for e in last_errors}
        if last_codes & {"segment_timeout", "segment_call_failed"}:
            call_failure_count = attempt_count
        elif last_parsed_result is not None:
            qc_rounds = attempt_count
    if call_failure_count >= ScriptSplitConstants.SEGMENT_MAX_RETRIES:
        _handle_segment_exhausted(task, seg, registry)
    if enable_qc and qc_rounds >= qc_max_rounds and last_parsed_result is not None:
        forced_errors = _mark_forced_accept_errors(last_errors)
        logger.warning(
            "task %s 段 %d 质检修正已达到上限 %d 轮，强制采用检查点中的最后候选；issues=%s",
            task.id,
            seg.segment_index,
            qc_max_rounds,
            [error.get("code", "unknown") for error in forced_errors],
        )
        _complete_segment_result(
            task=task,
            seg=seg,
            parsed=last_parsed_result,
            strategy=strategy,
            plan=plan,
            registry=registry,
            total=total,
            parallel_child=_parallel_child,
            validation_errors=forced_errors,
        )
        return

    generation_attempt = attempt_count + 1
    qc_feedback = _build_qc_feedback(last_errors, seg) if last_errors else None

    try:
        parsed = await asyncio.wait_for(
            parse_script_to_shots(
                script_content=seg.source_content,
                max_group_duration=cfg.get("max_group_duration", 15),
                world_id=cfg.get("world_id"),
                model=cfg.get("model"),
                temperature=cfg.get("temperature", 0.7),
                force_medium_shot=cfg.get("force_medium_shot", False),
                no_bg_music=cfg.get("no_bg_music", False),
                split_multi_dialogue=cfg.get("split_multi_dialogue", False),
                language=cfg.get("language"),
                dialogue_language=cfg.get("dialogue_language"),
                prompt_language=cfg.get("prompt_language"),
                auth_token=task.auth_token,
                vendor_id=cfg.get("vendor_id"),
                model_id=cfg.get("model_id"),
                enable_thinking=cfg.get("enable_thinking", False),
                thinking_effort=cfg.get("thinking_effort", "medium"),
                previous_parsed_result=last_parsed_result,
                qc_feedback=qc_feedback,
                segment_context=segment_context,
                strict_json=True,
            ),
            timeout=ScriptSplitConstants.LLM_CALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        call_failure_count += 1
        errors = [{"code": "segment_timeout", "severity": "error",
                   "message": f"段 {seg.segment_index} 第 {generation_attempt} 次生成超时",
                   "_call_failure_count": call_failure_count, "_qc_round": qc_rounds}]
        ScriptSplitSegmentModel.save_failure(task.id, seg.segment_index, errors)
        logger.warning("task %s 段 %d 第 %d 次超时", task.id, seg.segment_index, generation_attempt)
        if call_failure_count >= ScriptSplitConstants.SEGMENT_MAX_RETRIES:
            _handle_segment_exhausted(task, seg, registry)
        return
    except Exception as e:
        msg = str(e)
        if _is_auth_error(msg):
            raise WaitingAuth()
        call_failure_count += 1
        errors = [{"code": "segment_call_failed", "severity": "error", "message": msg,
                   "_call_failure_count": call_failure_count, "_qc_round": qc_rounds}]
        ScriptSplitSegmentModel.save_failure(task.id, seg.segment_index, errors)
        logger.warning("task %s 段 %d 第 %d 次调用失败: %s",
                       task.id, seg.segment_index, generation_attempt, msg)
        if call_failure_count >= ScriptSplitConstants.SEGMENT_MAX_RETRIES:
            _handle_segment_exhausted(task, seg, registry)
        return

    # 并发请求可能在模型返回前被用户取消；迟到结果不得写入检查点。
    if _is_cancelled(task.id):
        raise CancelledByUser()

    errors: List[Dict[str, Any]] = list(
        strategy.validate_segment_result(parsed, plan, seg.segment_id) or []
    )
    if enable_qc:
        current_qc_round = qc_rounds + 1
        qc_errors = await _run_enabled_segment_qc(
            parsed=parsed,
            registry=registry,
            segment=seg,
            config=cfg,
            task=task,
            qc_round=current_qc_round,
        )
        errors.extend(qc_errors)
    if errors:
        current_qc_round = qc_rounds + 1
        errors = [dict(error, _qc_round=current_qc_round,
                       _call_failure_count=call_failure_count) for error in errors]
        logger.warning("task %s 段 %d 第 %d 次校验失败: %s",
                       task.id, seg.segment_index, generation_attempt, errors)
        if current_qc_round >= qc_max_rounds:
            forced_errors = _mark_forced_accept_errors(errors)
            logger.warning(
                "task %s 段 %d 质检修正已达到上限 %d 轮，强制采用当前最后候选；issues=%s",
                task.id,
                seg.segment_index,
                qc_max_rounds,
                [error.get("code", "unknown") for error in forced_errors],
            )
            _complete_segment_result(
                task=task,
                seg=seg,
                parsed=parsed,
                strategy=strategy,
                plan=plan,
                registry=registry,
                total=total,
                parallel_child=_parallel_child,
                validation_errors=forced_errors,
            )
            return
        ScriptSplitSegmentModel.save_failure(
            task.id,
            seg.segment_index,
            errors,
            parsed_result=parsed,
        )
        return

    _complete_segment_result(
        task=task,
        seg=seg,
        parsed=parsed,
        strategy=strategy,
        plan=plan,
        registry=registry,
        total=total,
        parallel_child=_parallel_child,
    )


def _mark_forced_accept_errors(
    errors: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """保留最后一轮 QC 问题，并标记该段是达到上限后强制接纳。"""
    return [dict(error, _forced_accept=True) for error in errors]


def _complete_segment_result(
    task: ScriptSplitTask,
    seg,
    parsed: Dict[str, Any],
    strategy,
    plan: Dict[str, Any],
    registry: AcceptedRegistry,
    total: int,
    parallel_child: bool = False,
    validation_errors: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """统一提交正常通过或 QC 耗尽后强制接纳的段结果。"""
    continuity_out = _extract_continuity_out(parsed)
    if parallel_child:
        contract = strategy.build_segment_context(plan, seg.segment_id).get(
            "spatial_contract", {}
        )
        ScriptSplitSegmentModel.save_success(
            task.id,
            seg.segment_index,
            parsed,
            continuity_out,
            continuity_in=contract.get("continuity_in") or {},
            validation_errors=validation_errors,
        )
        return

    _commit_segment_entities(parsed, registry)
    ScriptSplitSegmentModel.save_success(
        task.id,
        seg.segment_index,
        parsed,
        continuity_out,
        continuity_in=task.get_continuity_state(),
        validation_errors=validation_errors,
    )
    ScriptSplitTaskModel.save_field(
        task.id,
        accepted_registry_json=registry.to_context(),
        continuity_state_json=continuity_out,
    )
    ScriptSplitTaskModel.increment_completed(task.id)
    progress = 10 + int(75 * (task.completed_segment_count + 1) / total)
    ScriptSplitTaskModel.update_status(
        task.id,
        ScriptSplitConstants.STATUS_GENERATING,
        phase="segment_generation",
        progress=min(progress, 84),
    )


async def _step_generate_parallel_batch(task: ScriptSplitTask, strategy) -> None:
    """并发生成效果模式的一批独立段，并在批次结束后统一结算检查点。"""
    segments = ScriptSplitSegmentModel.get_uncompleted(
        task.id,
        ScriptSplitConstants.QUALITY_SEGMENT_PARALLELISM,
    )
    if not segments:
        await step_merge(task)
        return
    if _is_cancelled(task.id):
        raise CancelledByUser()

    ScriptSplitTaskModel.save_field(
        task.id,
        current_segment_index=min(seg.segment_index for seg in segments),
    )
    results = await asyncio.gather(
        *(
            step_generate_segment(task, _segment=seg, _parallel_child=True)
            for seg in segments
        ),
        return_exceptions=True,
    )

    completed = ScriptSplitSegmentModel.count_by_status(
        task.id,
        SEGMENT_STATUS_COMPLETED,
    )
    next_segment = ScriptSplitSegmentModel.get_first_uncompleted(task.id)
    total = int(task.total_segment_count or 1)
    progress = 10 + int(75 * completed / total)
    ScriptSplitTaskModel.save_field(
        task.id,
        completed_segment_count=completed,
        current_segment_index=(next_segment.segment_index if next_segment else total),
    )
    ScriptSplitTaskModel.update_status(
        task.id,
        ScriptSplitConstants.STATUS_GENERATING,
        phase="segment_generation",
        progress=min(progress, 84),
    )

    for error_type in (WaitingAuth, CancelledByUser, TaskPaused, EngineError):
        for result in results:
            if isinstance(result, error_type):
                raise result
    for result in results:
        if isinstance(result, BaseException):
            raise EngineError("parallel_segment_failed", str(result))

    if completed == total:
        refreshed = ScriptSplitTaskModel.get_by_id(task.id) or task
        await step_merge(refreshed)


def _handle_segment_exhausted(task: ScriptSplitTask, seg, registry) -> None:
    """单段重试耗尽后暂停；不再自动重建分段计划和检查点。"""
    raise TaskPaused(
        "segment_max_retries",
        f"段 {seg.segment_index} 达到重试上限 {ScriptSplitConstants.SEGMENT_MAX_RETRIES}",
    )


# ---- 单步：合并与全局校验 ----

async def step_merge(task: ScriptSplitTask) -> None:
    """合并全部分段，执行全局规范化与质检。"""
    completed = ScriptSplitSegmentModel.get_completed(task.id)
    expected = int(task.total_segment_count or 0)
    if expected <= 0 or len(completed) != expected:
        raise EngineError(
            "invalid_segment_checkpoint_state",
            f"分段检查点不完整：expected={expected}, completed={len(completed)}",
        )

    merged = _merge_segments(completed)
    # 全局资产清理 + 空间修复 + 分组重排（复用 script_parser 后处理）
    from llm.script_parser import (
        sanitize_parsed_prop_references,
        sanitize_parsed_location_references,
        repair_spatial_layout_continuity,
        reorganize_shot_groups,
    )
    cfg = task.get_request_config()
    strategy = get_script_split_strategy(cfg.get("sequence_mode", "speed"))
    db_locations = None
    world_id = cfg.get("world_id")
    if world_id not in (None, ""):
        from model.location import LocationModel

        # 合并阶段必须重新加载当前世界的完整场景树。分段解析结果中的
        # location_db_id 已经过单段校验；若这里不给 sanitizer 数据库视图，
        # 它会把所有非空 DB id 都误判成模型编造值并清空 shot.location_id。
        db_locations = await asyncio.to_thread(
            LocationModel.get_tree_by_world,
            int(world_id),
            None,
        )
    if strategy.parallel_enabled:
        try:
            merged = strategy.repair_merged_result(
                merged,
                task.get_segment_plan() or {},
            )
        except ValueError as exc:
            raise EngineError("quality_merge_invalid", str(exc)) from exc
        # 先恢复规划阶段的全局注册表，再清理引用，避免并发段只返回实体子集时误删合法 ID。
        merged = sanitize_parsed_prop_references(merged)
        merged = sanitize_parsed_location_references(merged, db_locations)
    else:
        merged = sanitize_parsed_prop_references(merged)
        merged = sanitize_parsed_location_references(merged, db_locations)
        merged = repair_spatial_layout_continuity(merged)
    merged = reorganize_shot_groups(
        merged, cfg.get("max_group_duration", 15))

    merged = renumber_global(merged)
    ScriptSplitTaskModel.save_field(task.id, final_result_json=merged)
    ScriptSplitTaskModel.update_status(
        task.id, ScriptSplitConstants.STATUS_PUBLISHING,
        phase="publishing", progress=95,
    )


# ---- 单步：故事板发布（仅 storyboard 来源）----

async def step_publish(task: ScriptSplitTask) -> None:
    """故事板来源的发布：把 final_result 物化为 storyboard_scene（幂等）。

    见设计文档 §15。视频工作流来源不经过发布（前端自行物化节点）。
    """
    cfg = task.get_request_config()
    if cfg.get("source") != "storyboard":
        # 非故事板来源：直接标记完成
        ScriptSplitTaskModel.update_status(
            task.id, ScriptSplitConstants.STATUS_COMPLETED,
            phase="done", progress=100,
        )
        return

    storyboard_id = cfg.get("storyboard_id")
    if not storyboard_id:
        raise EngineError("no_storyboard_id", "故事板任务缺少 storyboard_id")

    final_result = task.get_final_result()
    if not final_result:
        raise EngineError("no_final_result", "无最终结果可发布")

    # 幂等恢复：检查是否已全部落库
    from model.storyboard import StoryboardModel, StoryboardSceneModel
    expected_count = sum(
        len(g.get("shots", []) or [])
        for g in (final_result.get("shot_groups") or [])
    )
    existing_count = await asyncio.to_thread(
        StoryboardModel.count_scenes_by_split_task, task.id
    )
    if existing_count > 0:
        if existing_count == expected_count:
            # 已全部发布，直接标记完成
            ScriptSplitTaskModel.update_status(
                task.id, ScriptSplitConstants.STATUS_COMPLETED,
                phase="done", progress=100,
            )
            return
        # 存在但不完整或有冲突：按设计文档 §15 停止发布
        raise EngineError(
            "publish_conflict",
            f"故事板已有 {existing_count} 个分镜（预期 {expected_count}），"
            f"可能存在手工分镜或发布中断残留，停止发布避免重复",
        )

    # 再次检查故事板是否已有非本任务的分镜
    existing_scenes = await asyncio.to_thread(
        StoryboardSceneModel.list_by_storyboard, storyboard_id
    )
    if existing_scenes:
        raise EngineError(
            "storyboard_has_scenes",
            "故事板已存在分镜，不能重复生成",
        )

    # 1. 场景资产化（location bootstrap）
    from services.storyboard_location_bootstrap_service import (
        StoryboardLocationBootstrapService,
    )
    world_id = cfg.get("world_id")
    if world_id:
        await asyncio.to_thread(
            StoryboardLocationBootstrapService().bootstrap,
            final_result, world_id, task.user_id,
        )

    # 2. 构造 scenes_payload
    from api.storyboard import build_storyboard_scenes_from_parsed_script
    style = ""
    try:
        sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
        if sb:
            style = sb.style or ""
    except Exception:
        pass
    scenes_payload = await asyncio.to_thread(
        build_storyboard_scenes_from_parsed_script, final_result, style
    )

    # 3. 幂等创建分镜（带 script_split_task_id + source_shot_key）
    await asyncio.to_thread(
        StoryboardModel.create_scenes,
        storyboard_id, task.user_id, scenes_payload, task.id,
    )

    ScriptSplitTaskModel.update_status(
        task.id, ScriptSplitConstants.STATUS_COMPLETED,
        phase="done", progress=100,
    )
    logger.info("task %s 发布完成，storyboard %s 创建 %d 个分镜",
                task.id, storyboard_id, len(scenes_payload))


def _merge_segments(segments) -> Dict[str, Any]:
    """按 segment_index 顺序拼接已完成段的 parsed_data。"""
    merged: Dict[str, Any] = {
        "script_title": "",
        "characters": [],
        "locations": [],
        "props": [],
        "spatial_world": {"space_units": []},
        "shot_groups": [],
        "metadata": {},
    }
    seen_char = set()
    seen_loc = set()
    seen_prop = set()
    seen_space = set()
    total_dur = 0.0
    for seg in segments:
        parsed = seg.get_parsed_result() or {}
        if parsed.get("script_title") and not merged["script_title"]:
            merged["script_title"] = parsed["script_title"]
        # 实体去重合并（按 id）
        for c in parsed.get("characters", []) or []:
            if isinstance(c, dict) and c.get("id") not in seen_char:
                merged["characters"].append(c)
                seen_char.add(c.get("id"))
        for l in parsed.get("locations", []) or []:
            if isinstance(l, dict) and l.get("id") not in seen_loc:
                merged["locations"].append(l)
                seen_loc.add(l.get("id"))
        for p in parsed.get("props", []) or []:
            if isinstance(p, dict) and p.get("id") not in seen_prop:
                merged["props"].append(p)
                seen_prop.add(p.get("id"))
        for su in (parsed.get("spatial_world", {}) or {}).get("space_units", []) or []:
            if isinstance(su, dict) and su.get("space_unit_id") not in seen_space:
                merged["spatial_world"]["space_units"].append(su)
                seen_space.add(su.get("space_unit_id"))
        for g in parsed.get("shot_groups", []) or []:
            for s in g.get("shots", []) or []:
                dur = s.get("duration")
                if isinstance(dur, (int, float)):
                    total_dur += dur
                s["_segment_id"] = seg.segment_id
                s["_source_block_ids"] = seg.get_block_ids()
            merged["shot_groups"].append(g)
    merged["total_duration"] = int(total_dur)
    return merged


# ---- 辅助函数 ----

def _load_registry(task: ScriptSplitTask) -> AcceptedRegistry:
    """从 task.accepted_registry_json 重建 registry。"""
    reg = AcceptedRegistry()
    data = task.get_accepted_registry() or {}
    for c in data.get("characters", []) or []:
        if isinstance(c, dict) and c.get("id"):
            reg.commit_entity("character", c["id"], c)
    for l in data.get("locations", []) or []:
        if isinstance(l, dict) and l.get("id"):
            reg.commit_entity("location", l["id"], l)
    for p in data.get("props", []) or []:
        if isinstance(p, dict) and p.get("id"):
            reg.commit_entity("prop", p["id"], p)
    reg.spatial_world = data.get("spatial_world") or {"space_units": []}
    return reg


def _build_segment_context(task: ScriptSplitTask, seg, registry: AcceptedRegistry) -> Dict[str, Any]:
    """构建传给 parse_script_to_shots 的 segment_context。"""
    # 上一段尾部镜头摘要
    tail = []
    prev_segs = ScriptSplitSegmentModel.get_completed(task.id)
    if prev_segs:
        last = prev_segs[-1]
        last_parsed = last.get_parsed_result() or {}
        groups = last_parsed.get("shot_groups", []) or []
        shots = [s for g in groups for s in (g.get("shots", []) or [])]
        tail = shots[-ScriptSplitConstants.HISTORY_TAIL_SHOTS:] if shots else []

    return {
        "task_id": task.id,
        "segment_id": seg.segment_id,
        "segment_index": seg.segment_index,
        "total_segments": task.total_segment_count,
        "accepted_registry": registry.to_context(),
        "previous_tail_summary": tail,
        "continuity_state": task.get_continuity_state(),
        "id_reservations": registry.id_reservations(),
        "source_block_ids": seg.get_block_ids(),
    }


async def _run_enabled_segment_qc(
    parsed: Dict[str, Any],
    registry: AcceptedRegistry,
    segment: Any,
    config: Dict[str, Any],
    task: ScriptSplitTask,
    qc_round: int = 1,
) -> List[Dict[str, Any]]:
    """运行开启状态下的两套段级质检并汇总错误，不做短路。"""
    _local_ok, local_errors = _validate_segment(parsed, registry)
    errors = list(local_errors or [])
    qc_log_context = create_qc_log_context(
        task_id=task.id,
        segment_id=segment.segment_id,
        segment_index=segment.segment_index,
        qc_round=qc_round,
    )
    try:
        report = await asyncio.wait_for(
            run_script_split_qc(
                parsed_data=parsed,
                script_content=segment.source_content or "",
                dialogue_language=config.get("dialogue_language") or "",
                prompt_language=config.get("prompt_language") or "",
                max_group_duration=config.get("max_group_duration", 15),
                use_llm=False,
                model=config.get("model"),
                vendor_id=config.get("vendor_id"),
                model_id=config.get("model_id"),
                auth_token=task.auth_token,
                enable_thinking=config.get("enable_thinking", False),
                thinking_effort=config.get("thinking_effort", "medium"),
                known_characters=registry.to_context().get("characters", []),
                log_context=qc_log_context,
            ),
            timeout=ScriptSplitConstants.WORKER_STEP_TIMEOUT_SECONDS,
        )
        if not report.passed:
            for issue in report.issues:
                if hasattr(issue, "to_dict"):
                    errors.append(issue.to_dict())
                elif isinstance(issue, dict):
                    errors.append(dict(issue))
    except Exception as exc:
        errors.append({
            "code": "qc_agent_failed",
            "severity": "error",
            "message": str(exc) or "质检智能体执行失败",
        })
    return errors


def _validate_segment(parsed: Dict[str, Any], registry: AcceptedRegistry) -> Tuple[bool, List[Dict[str, Any]]]:
    """单段综合校验：实体 ID 策略 + 空间引用完整性。"""
    ok1, errs1 = validate_segment_entities(parsed, registry)
    ok2, errs2 = validate_segment_spatial_references(parsed, registry)
    return (ok1 and ok2), (errs1 + errs2)


def _commit_segment_entities(parsed: Dict[str, Any], registry: AcceptedRegistry) -> None:
    """段通过后把新实体 commit 到 registry。"""
    for c in parsed.get("characters", []) or []:
        if isinstance(c, dict) and c.get("id") and c["id"] not in registry.characters:
            registry.commit_entity("character", c["id"], c)
    for l in parsed.get("locations", []) or []:
        if isinstance(l, dict) and l.get("id") and l["id"] not in registry.locations:
            registry.commit_entity("location", l["id"], l)
    for p in parsed.get("props", []) or []:
        if isinstance(p, dict) and p.get("id") and p["id"] not in registry.props:
            registry.commit_entity("prop", p["id"], p)
    registry.commit_spatial_world(parsed.get("spatial_world", {}) or {})


def _extract_continuity_out(parsed: Dict[str, Any]) -> Dict[str, Any]:
    """从段结果提取结束时的空间连续性状态。"""
    groups = parsed.get("shot_groups", []) or []
    shots = [s for g in groups for s in (g.get("shots", []) or [])]
    if not shots:
        return {}
    last = shots[-1]
    sl = last.get("spatial_layout", {}) or {}
    return {
        "last_shot_id": last.get("shot_id"),
        "last_location_id": last.get("location_id"),
        "last_characters_present": last.get("characters_present", []),
        "last_spatial_layout": sl,
    }


def _build_qc_feedback(errors: List[Dict[str, Any]], seg) -> Dict[str, Any]:
    """把段级错误列表构造成 qc_feedback（复用 script_parser 的 qc_retry_block 通道）。"""
    issues = []
    for e in errors:
        issues.append({
            "severity": e.get("severity", "error"),
            "code": e.get("code", "unknown"),
            "shot_ref": e.get("shot_ref", ""),
            "field": e.get("field") or e.get("path", ""),
            "message": e.get("message", str(e)),
        })
    return {
        "summary": f"段 {seg.segment_index}（segment_id={seg.segment_id}）"
                   f"校验未通过，请修复后重新输出**当前段完整**的 shot_groups JSON：",
        "issues": issues,
    }


def _format_plan_errors(errors: List[Dict[str, Any]]) -> str:
    lines = ["上一版分段计划校验失败，请修正："]
    for e in errors:
        lines.append(f"- [{e.get('code')}] {e.get('message')}")
    return "\n".join(lines)


def _is_cancelled(task_id: int) -> bool:
    return ScriptSplitTaskModel.is_cancel_requested(task_id)


def _is_auth_error(msg: str) -> bool:
    """判断是否鉴权类错误。"""
    m = msg.lower()
    return any(k in m for k in ("401", "unauthorized", "invalid_api_key",
                                 "auth", "token", "鉴权", "permission_denied"))


__all__ = [
    "EngineError",
    "TaskPaused",
    "CancelledByUser",
    "WaitingAuth",
    "step_plan",
    "step_generate_segment",
    "step_merge",
    "step_publish",
]
