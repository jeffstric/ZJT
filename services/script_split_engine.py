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
import functools
from copy import deepcopy
from datetime import datetime
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
    rewrite_segment_entity_ids,
    validate_segment_entities,
    validate_segment_spatial_references,
    renumber_global,
)
from services.script_split_strategy import get_script_split_strategy
from services.storyboard_quality_sequence import (
    get_storyboard_quality_sequence_strategy,
)
from services.script_split_character_contract import (
    CHARACTER_CONTRACT_CONFIG_KEY,
    first_character_contract_error_message,
    validate_segment_character_contract,
)
from services.location_structure_guard import (
    bind_and_validate_planned_locations,
    flatten_db_locations,
    validate_full_location_structure,
    validate_segment_location_structure_extended,
    validate_segment_new_roots,
)
from model.script_split_task import ScriptSplitTaskModel, ScriptSplitTask
from utils.sentry_util import SentryUtil
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


async def _load_current_db_locations(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """异步读取当前世界场景树，供独立结构硬门禁使用。"""
    world_id = config.get("world_id")
    if world_id in (None, ""):
        return []
    from model.location import LocationModel

    return await asyncio.to_thread(
        LocationModel.get_tree_by_world,
        int(world_id),
        None,
    ) or []


async def _ensure_task_character_contract(
    task: ScriptSplitTask,
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """返回任务级不可变角色快照，并为升级前活跃任务补齐一次。"""
    existing = config.get(CHARACTER_CONTRACT_CONFIG_KEY)
    if isinstance(existing, dict) and isinstance(existing.get("characters"), list):
        return existing
    # 新任务一定在 API 创建阶段持久化数据库快照。升级前活跃任务不能在 worker
    # 中重新读一个随时间变化的角色库，只能用已接受注册表固化兼容快照。
    registry_characters = (task.get_accepted_registry() or {}).get("characters") or []
    contract_characters = []
    for character in registry_characters:
        if not isinstance(character, dict):
            continue
        db_id = character.get("character_db_id")
        name = str(character.get("name") or "").strip()
        if db_id in (None, "") or not name:
            continue
        contract_characters.append({
            "character_db_id": db_id,
            "canonical_name": name,
        })
    contract = {
        "version": ScriptSplitConstants.CHARACTER_CONTRACT_VERSION,
        "world_id": config.get("world_id"),
        "characters": contract_characters,
        "legacy_fallback": True,
    }
    config[CHARACTER_CONTRACT_CONFIG_KEY] = contract
    # 兼容快照只存在当前内存任务中；新任务的数据库快照已由 API 创建阶段持久化。
    # 不在 worker 中写回基于历史结果推导的弱真值，避免把它误当成数据库权威快照。
    task.request_config = config
    return contract


async def _validate_segment_location_structure(
    parsed: Dict[str, Any],
    config: Dict[str, Any],
    plan: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """L1：段级扩展硬门禁（locations + space_unit/registry 引用）。"""
    return validate_segment_location_structure_extended(
        parsed,
        await _load_current_db_locations(config),
        plan=plan,
    )


def _planned_location_hard_errors(
    plan: Dict[str, Any],
    db_locations: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], bool]:
    """对已编译 plan 的 registry locations 做 L0 复检。

    validate_full_location_structure 会把可修复的父级冲突就地按数据库层级
    对齐在 bound 副本上；这里将修复后的 bound 回写 compiled_registry.locations，
    并返回 (errors, locations_changed)。locations_changed 为 True 时调用方必须
    持久化（见 _persist_realigned_plan_locations），否则 compiled_registry、
    segment_plan_json 与 accepted_registry_json 会继续携带旧层级下发段生成。
    """
    registry = plan.get("compiled_registry") or {}
    if not isinstance(registry, dict):
        return [], False
    locations = registry.get("locations") or []
    if not locations:
        return [], False
    bound, errors = bind_and_validate_planned_locations(
        locations,
        db_locations,
        spatial_world=registry.get("spatial_world")
        if isinstance(registry.get("spatial_world"), dict)
        else plan.get("spatial_world"),
    )
    changed = bound != locations
    if changed:
        registry["locations"] = bound
    return errors, changed


def _persist_realigned_plan_locations(task: ScriptSplitTask, plan: Dict[str, Any]) -> None:
    """L0 复检按数据库层级修复规划 locations 后，持久化 plan 并同步 accepted registry。

    accepted_registry 在生成期可能已接纳段级新实体，不能整体用 compiled_registry
    覆盖；仅按内部 id 用修复后的规划 locations 更新对应条目。
    """
    registry = plan.get("compiled_registry") or {}
    bound_locations = [
        item for item in (registry.get("locations") or [])
        if isinstance(item, dict)
    ]
    ScriptSplitTaskModel.save_field(task.id, segment_plan_json=plan)
    accepted = task.get_accepted_registry()
    if not isinstance(accepted, dict):
        return
    accepted_locations = accepted.get("locations")
    if not isinstance(accepted_locations, list) or not accepted_locations:
        return
    bound_by_id = {
        str(loc.get("id")): loc
        for loc in bound_locations
        if loc.get("id") not in (None, "")
    }
    updated = False
    for index, loc in enumerate(accepted_locations):
        if not isinstance(loc, dict):
            continue
        repaired = bound_by_id.get(str(loc.get("id") or ""))
        if repaired is not None and repaired != loc:
            accepted_locations[index] = deepcopy(repaired)
            updated = True
    if updated:
        ScriptSplitTaskModel.save_field(task.id, accepted_registry_json=accepted)


async def _revalidate_saved_full_location_graph(
    task_id: int,
    current_segment: Any,
    current_parsed: Dict[str, Any],
    config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """恢复合并级硬错误时，用所有保存候选重建全量 location 图复检。"""
    segments = await asyncio.to_thread(ScriptSplitSegmentModel.get_all, task_id)
    locations: List[Dict[str, Any]] = []
    for segment in segments:
        parsed = (
            current_parsed
            if int(segment.segment_index) == int(current_segment.segment_index)
            else segment.get_parsed_result()
        ) or {}
        locations.extend(
            location for location in (parsed.get("locations") or [])
            if isinstance(location, dict)
        )
    return validate_full_location_structure(
        {"locations": locations},
        await _load_current_db_locations(config),
    )


def _first_hard_gate_error(errors: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    return next(
        (error for error in errors if isinstance(error, dict) and error.get("_hard_gate")),
        None,
    )


def _pause_for_hard_gate(errors: List[Dict[str, Any]]) -> None:
    first = _first_hard_gate_error(errors) or {}
    raise TaskPaused(
        str(first.get("code") or "location_structure_invalid"),
        str(first.get("message") or "场景父级结构不合法，请修正后继续"),
    )


def _pause_for_character_contract(errors: List[Dict[str, Any]]) -> None:
    raise TaskPaused(
        ScriptSplitConstants.ERROR_CHARACTER_PROMPT_CONTRACT_INVALID,
        first_character_contract_error_message(errors),
    )


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

    # 已有计划：L0 复检（历史 plan 可能含非法新顶层）；不通过则清空并重规划
    existing_plan = task.get_segment_plan()
    if existing_plan:
        db_locations = await _load_current_db_locations(cfg)
        hard_errors, locations_realigned = _planned_location_hard_errors(
            existing_plan, db_locations,
        )
        if not hard_errors:
            if locations_realigned:
                # 父级冲突已按数据库自动对齐：回写持久化，避免旧层级继续下发
                _persist_realigned_plan_locations(task, existing_plan)
            logger.info("task %s 已有分段计划，跳过规划", task.id)
            return
        logger.warning(
            "task %s 已有计划未通过场景结构 L0 复检，将重规划: %s",
            task.id,
            [error.get("code") for error in hard_errors],
        )
        # save_field 会跳过 None；用空对象清空计划，迫使本步重新规划
        ScriptSplitTaskModel.save_field(
            task.id,
            segment_plan_json={},
            accepted_registry_json={},
            total_segment_count=0,
            completed_segment_count=0,
        )

    anchors = anchorize_script(script)
    if not anchors:
        raise EngineError("empty_script", "剧本为空，无法分段")

    db_locations = await _load_current_db_locations(cfg)
    plan = None
    planning_prompt = strategy.build_planning_prompt(
        anchors,
        ScriptSplitConstants.SEGMENT_MAX_OUTPUT_TOKENS,
        db_locations=db_locations,
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
                model=cfg.get("model") or "deepseek-v4-flash",
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
                compiled_plan = strategy.compile_plan(
                    raw_plan,
                    anchors,
                    db_locations=db_locations,
                )
            except ValueError as exc:
                ok = False
                message = str(exc)
                code = "quality_plan_invalid"
                if "new_root_location_forbidden" in message:
                    code = "new_root_location_forbidden"
                elif "location_parent" in message:
                    code = "location_parent_invalid"
                elif "planned_space_unit_location_unbound" in message:
                    code = "planned_space_unit_location_unbound"
                errors = [{
                    "code": code,
                    "message": message,
                    "_hard_gate": code != "quality_plan_invalid",
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
        first = (last_errors[0] if last_errors else {}) or {}
        detail = first.get("message") or (
            f"规划失败，已重试 {ScriptSplitConstants.PLAN_MAX_RETRIES} 次"
        )
        raise TaskPaused(
            str(first.get("code") or "plan_failed"),
            str(detail),
        )

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
    _all_segments=None,
) -> None:
    """生成下一个未完成段（断点续传从第一个未完成段继续）。

    调用失败受 SEGMENT_MAX_RETRIES 保护；质检最多修正 qc_max_rounds 轮，
    耗尽后采用最后一轮合法候选继续。
    """
    from llm.script_parser import parse_script_to_shots
    cfg = task.get_request_config()
    strategy = get_script_split_strategy(cfg.get("sequence_mode", "speed"))
    plan = task.get_segment_plan() or {}
    character_contract = await _ensure_task_character_contract(task, cfg)
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
    segment_context.update(strategy.build_segment_context(plan, seg.segment_id))
    if _parallel_child:
        # 依赖感知：优先用 build_runtime_segment_context（按依赖类型注入真实 handoff，
        # 见设计文档 §9.2/§20.2）。仅当策略未提供该方法（如非 quality）时回退到旧逻辑。
        if _all_segments is not None and hasattr(strategy, "build_runtime_segment_context"):
            segment_context.update(
                strategy.build_runtime_segment_context(plan, seg, _all_segments)
            )
        else:
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
    character_hard_rounds = max(
        [int(e.get("_character_hard_round", 0) or 0) for e in last_errors] or [0]
    )
    # 兼容升级前没有内部计数元数据的失败检查点。显式存在值为 0 的元数据
    # 表示用户已经开启新重试周期，不能再由全生命周期 attempt_count 覆盖。
    has_retry_metadata = any(
        isinstance(error, dict)
        and (
            "_call_failure_count" in error
            or "_qc_round" in error
            or "_character_hard_round" in error
        )
        for error in last_errors
    )
    if last_errors and not has_retry_metadata:
        last_codes = {e.get("code") for e in last_errors}
        if last_codes & {"segment_timeout", "segment_call_failed"}:
            call_failure_count = attempt_count
        elif last_parsed_result is not None:
            qc_rounds = attempt_count
    checkpoint_hard_errors: List[Dict[str, Any]] = []
    checkpoint_character_errors: List[Dict[str, Any]] = []
    if last_parsed_result is not None:
        # 恢复检查点时必须使用最新数据库重新执行硬门禁。用户补齐顶层场景后，
        # 保存的完整候选可以直接恢复；旧的 _forced_accept 标记不能绕过该检查。
        checkpoint_hard_errors = await _validate_segment_location_structure(
            last_parsed_result,
            cfg,
            plan=plan,
        )
        previous_full_hard_errors = [
            error for error in last_errors
            if isinstance(error, dict)
            and error.get("_hard_gate")
            and error.get("_hard_gate_type") != "character_prompt"
            and error.get("code") != "new_root_location_forbidden"
        ]
        if previous_full_hard_errors:
            checkpoint_hard_errors = await _revalidate_saved_full_location_graph(
                task.id,
                seg,
                last_parsed_result,
                cfg,
            )
        checkpoint_character_errors = validate_segment_character_contract(
            last_parsed_result,
            character_contract,
            registry.to_context(),
        )
        checkpoint_hard_errors.extend(checkpoint_character_errors)
        if not checkpoint_hard_errors:
            last_errors = [
                error for error in last_errors
                if not (isinstance(error, dict) and error.get("_hard_gate"))
            ]
            if not last_errors:
                _complete_segment_result(
                    task=task,
                    seg=seg,
                    parsed=last_parsed_result,
                    strategy=strategy,
                    plan=plan,
                    registry=registry,
                    total=total,
                    parallel_child=_parallel_child,
                )
                return
    if (
        checkpoint_character_errors
        and character_hard_rounds
        >= ScriptSplitConstants.CHARACTER_PROMPT_VALIDATION_MAX_RETRIES
    ):
        _pause_for_character_contract(checkpoint_character_errors)
    if checkpoint_hard_errors and not checkpoint_character_errors and not enable_qc:
        _pause_for_hard_gate(checkpoint_hard_errors)
    if call_failure_count >= ScriptSplitConstants.SEGMENT_MAX_RETRIES:
        if checkpoint_character_errors:
            _pause_for_character_contract(checkpoint_character_errors)
        if checkpoint_hard_errors:
            _pause_for_hard_gate(checkpoint_hard_errors)
        if last_parsed_result is not None:
            _complete_retry_exhausted_candidate(
                task, seg, last_parsed_result, last_errors,
                strategy, plan, registry, total, _parallel_child,
            )
            return
        _handle_segment_exhausted(task, seg, registry)
    if enable_qc and qc_rounds >= qc_max_rounds and last_parsed_result is not None:
        if checkpoint_character_errors:
            _pause_for_character_contract(checkpoint_character_errors)
        if checkpoint_hard_errors:
            _pause_for_hard_gate(checkpoint_hard_errors)
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
                character_contract=character_contract,
                strict_json=True,
                user_id=task.user_id,
                enable_character_appearance_changes=bool(
                    cfg.get(
                        "enable_character_variant",
                        ScriptSplitConstants.ENABLE_CHARACTER_VARIANT_DEFAULT,
                    )
                ),
            ),
            timeout=ScriptSplitConstants.LLM_CALL_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        call_failure_count += 1
        errors = [{"code": "segment_timeout", "severity": "error",
                   "message": f"段 {seg.segment_index} 第 {generation_attempt} 次生成超时",
                   "_call_failure_count": call_failure_count, "_qc_round": qc_rounds,
                   "_character_hard_round": character_hard_rounds}]
        ScriptSplitSegmentModel.save_failure(task.id, seg.segment_index, errors)
        logger.warning("task %s 段 %d 第 %d 次超时", task.id, seg.segment_index, generation_attempt)
        if call_failure_count >= ScriptSplitConstants.SEGMENT_MAX_RETRIES:
            if checkpoint_character_errors:
                _pause_for_character_contract(checkpoint_character_errors)
            if checkpoint_hard_errors:
                _pause_for_hard_gate(checkpoint_hard_errors)
            if last_parsed_result is not None:
                _complete_retry_exhausted_candidate(
                    task, seg, last_parsed_result, errors,
                    strategy, plan, registry, total, _parallel_child,
                )
                return
            _handle_segment_exhausted(task, seg, registry)
        return
    except Exception as e:
        msg = str(e)
        if _is_auth_error(msg):
            raise WaitingAuth()
        call_failure_count += 1
        errors = [{"code": "segment_call_failed", "severity": "error", "message": msg,
                   "_call_failure_count": call_failure_count, "_qc_round": qc_rounds,
                   "_character_hard_round": character_hard_rounds}]
        ScriptSplitSegmentModel.save_failure(task.id, seg.segment_index, errors)
        logger.warning("task %s 段 %d 第 %d 次调用失败: %s",
                       task.id, seg.segment_index, generation_attempt, msg)
        if call_failure_count >= ScriptSplitConstants.SEGMENT_MAX_RETRIES:
            if checkpoint_character_errors:
                _pause_for_character_contract(checkpoint_character_errors)
            if checkpoint_hard_errors:
                _pause_for_hard_gate(checkpoint_hard_errors)
            if last_parsed_result is not None:
                _complete_retry_exhausted_candidate(
                    task, seg, last_parsed_result, errors,
                    strategy, plan, registry, total, _parallel_child,
                )
                return
            _handle_segment_exhausted(task, seg, registry)
        return

    # 并发请求可能在模型返回前被用户取消；迟到结果不得写入检查点。
    if _is_cancelled(task.id):
        raise CancelledByUser()

    if hasattr(strategy, "materialize_segment_result"):
        materialized = strategy.materialize_segment_result(
            parsed,
            plan,
            seg.segment_id,
            segment_context,
        )
        parsed = materialized.parsed
        if hasattr(strategy, "write_materialization_logs"):
            await strategy.write_materialization_logs(
                task.id,
                seg.segment_id,
                parsed,
            )

    # 全局 ID 改写：name/db_id 复用 + loc_tmp_xxx 等临时 id 发号（先于一切实体校验）
    parsed = rewrite_segment_entity_ids(parsed, registry)

    hard_structure_errors = await _validate_segment_location_structure(
        parsed, cfg, plan=plan,
    )
    errors: List[Dict[str, Any]] = list(
        strategy.validate_segment_result(parsed, plan, seg.segment_id) or []
    )
    # 跨段空间校验（仅依赖段有 upstream_spatial_handoff，见设计文档 §12）
    upstream_handoff = segment_context.get("upstream_spatial_handoff")
    if upstream_handoff and hasattr(strategy, "validate_cross_segment"):
        errors.extend(
            strategy.validate_cross_segment(parsed, upstream_handoff, plan, seg.segment_id) or []
        )
    character_hard_errors = validate_segment_character_contract(
        parsed,
        character_contract,
        registry.to_context(),
    )
    if character_hard_errors:
        current_character_hard_round = character_hard_rounds + 1
        tagged_character_errors = [
            dict(
                error,
                _character_hard_round=current_character_hard_round,
                _qc_round=qc_rounds,
                _call_failure_count=call_failure_count,
            )
            for error in character_hard_errors
        ]
        tagged_location_errors = [
            dict(
                error,
                _hard_gate=True,
                _hard_gate_type="location_structure",
                _character_hard_round=current_character_hard_round,
                _qc_round=qc_rounds,
                _call_failure_count=call_failure_count,
            )
            for error in hard_structure_errors
        ]
        ScriptSplitSegmentModel.save_failure(
            task.id,
            seg.segment_index,
            tagged_character_errors + tagged_location_errors,
            parsed_result=parsed,
        )
        logger.warning(
            "task %s 段 %d 角色提示词硬校验第 %d/%d 轮失败: %s",
            task.id,
            seg.segment_index,
            current_character_hard_round,
            ScriptSplitConstants.CHARACTER_PROMPT_VALIDATION_MAX_RETRIES,
            [error.get("code") for error in tagged_character_errors],
        )
        if (
            current_character_hard_round
            >= ScriptSplitConstants.CHARACTER_PROMPT_VALIDATION_MAX_RETRIES
        ):
            _pause_for_character_contract(tagged_character_errors)
        return
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
    if hard_structure_errors:
        current_qc_round = qc_rounds + 1 if enable_qc else qc_rounds
        hard_structure_errors = [
            dict(
                error,
                _hard_gate=True,
                _hard_gate_type="location_structure",
                _qc_round=current_qc_round,
                _call_failure_count=call_failure_count,
            )
            for error in hard_structure_errors
        ]
        ordinary_errors = [
            dict(error, _qc_round=current_qc_round,
                 _call_failure_count=call_failure_count)
            for error in errors
        ]
        persisted_errors = hard_structure_errors + ordinary_errors
        ScriptSplitSegmentModel.save_failure(
            task.id,
            seg.segment_index,
            persisted_errors,
            parsed_result=parsed,
        )
        logger.warning(
            "task %s 段 %d 场景结构硬门禁失败: %s",
            task.id,
            seg.segment_index,
            [error.get("code") for error in hard_structure_errors],
        )
        if enable_qc and current_qc_round < qc_max_rounds:
            return
        _pause_for_hard_gate(hard_structure_errors)

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
    character_hard_errors = [
        error for error in errors
        if isinstance(error, dict)
        and error.get("_hard_gate")
        and error.get("_hard_gate_type") == "character_prompt"
    ]
    if character_hard_errors:
        _pause_for_character_contract(character_hard_errors)
    hard_error = _first_hard_gate_error(errors)
    if hard_error:
        _pause_for_hard_gate(errors)
    return [dict(error, _forced_accept=True) for error in errors]


def _complete_retry_exhausted_candidate(
    task: ScriptSplitTask,
    seg,
    parsed: Dict[str, Any],
    errors: List[Dict[str, Any]],
    strategy,
    plan: Dict[str, Any],
    registry: AcceptedRegistry,
    total: int,
    parallel_child: bool,
) -> None:
    """修正调用耗尽时采用最近一次成功解析的完整候选。"""
    forced_errors = _mark_forced_accept_errors(errors)
    logger.warning(
        "task %s 段 %d 调用重试已耗尽，强制采用最近一次可解析候选；issues=%s",
        task.id,
        seg.segment_index,
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
        parallel_child=parallel_child,
        validation_errors=forced_errors,
    )


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
    # 进度以段表 completed 实时计数为准，且相对历史 progress 只增不减。
    # 使用内存中的 task.progress，避免在单测/无 DB 环境下额外 get_by_id。
    prev_progress = int(getattr(task, "progress", None) or 0)
    ScriptSplitTaskModel.sync_generation_progress(
        task.id,
        total,
        previous_progress=prev_progress,
        current_segment_index=seg.segment_index,
    )


async def _step_generate_parallel_batch(task: ScriptSplitTask, strategy) -> None:
    """并发生成效果模式的一批 ready 段，并在批次结束后统一结算检查点。

    依赖感知调度（见设计文档 §8）：用 get_all 读取全量段，按 spatial_dependency
    选出 ready 集合。入口分流（§8.2 第 3 步）避免空 ready 时误调 step_merge。
    """
    all_segments = ScriptSplitSegmentModel.get_all(task.id)
    total = int(task.total_segment_count or len(all_segments) or 1)
    if _is_cancelled(task.id):
        raise CancelledByUser()

    plan = task.get_segment_plan() or {}
    # 策略支持 classify/select（quality），否则回退到旧的 get_uncompleted 逻辑
    if hasattr(strategy, "classify_segments"):
        ready, waiting_info, blocked = strategy.classify_segments(plan, all_segments)
        ready = ready[:ScriptSplitConstants.QUALITY_SEGMENT_PARALLELISM]
        if not ready:
            completed_now = ScriptSplitSegmentModel.count_by_status(
                task.id, SEGMENT_STATUS_COMPLETED,
            )
            if completed_now >= total:
                # 全部完成 → 合并
                refreshed = ScriptSplitTaskModel.get_by_id(task.id) or task
                await step_merge(refreshed)
                return
            if blocked:
                # 仅当依赖目标缺失、或上游 completed 却无候选时 blocked。
                # 上游 failed（等待重试）由 classify 归为 waiting，failed 段本身会进 ready。
                raise EngineError(
                    "quality_dependency_blocked",
                    f"task {task.id} 有 {len(blocked)} 个段依赖终态异常/缺失的上游，无法推进",
                )
            # 有 waiting 段但 ready 为空：正常等待上游（含上游 failed 重试中），让出 tick
            logger.info(
                "task %s 无 ready 段（%d 个 waiting），让出 tick",
                task.id, len(waiting_info),
            )
            return
        segments = ready
    else:
        # 非 quality 策略回退：取前 N 个未完成段
        segments = ScriptSplitSegmentModel.get_uncompleted(
            task.id,
            ScriptSplitConstants.QUALITY_SEGMENT_PARALLELISM,
        )
        if not segments:
            refreshed = ScriptSplitTaskModel.get_by_id(task.id) or task
            await step_merge(refreshed)
            return
        all_segments = segments  # 回退路径下下游无需跨段 handoff

    ScriptSplitTaskModel.save_field(
        task.id,
        current_segment_index=min(seg.segment_index for seg in segments),
    )
    results = await asyncio.gather(
        *(
            step_generate_segment(
                task, _segment=seg, _parallel_child=True, _all_segments=all_segments,
            )
            for seg in segments
        ),
        return_exceptions=True,
    )

    completed = ScriptSplitSegmentModel.count_by_status(
        task.id,
        SEGMENT_STATUS_COMPLETED,
    )
    next_segment = ScriptSplitSegmentModel.get_first_uncompleted(task.id)
    # 进度按段表实时 completed/total，且只增不减（避免硬门禁回退后 UI 倒退）
    prev_progress = int(getattr(task, "progress", None) or 0)
    current_idx = next_segment.segment_index if next_segment else total
    ScriptSplitTaskModel.sync_generation_progress(
        task.id,
        total,
        previous_progress=prev_progress,
        current_segment_index=current_idx,
    )
    # completed 变量供后续 merge 判断使用（与段表一致）
    completed = ScriptSplitTaskModel.count_completed_segments(task.id)

    for error_type in (WaitingAuth, CancelledByUser, TaskPaused, EngineError):
        for result in results:
            if isinstance(result, error_type):
                raise result
    for result in results:
        if isinstance(result, BaseException):
            try:
                logger.error(
                    "script_split parallel gather exception: %s",
                    result,
                    exc_info=(type(result), result, result.__traceback__),
                )
                SentryUtil.capture_exception(result)
            except Exception:
                logger.exception("script_split failed to record gather exception")
            raise EngineError("parallel_segment_failed", str(result))

    if completed == total:
        refreshed = ScriptSplitTaskModel.get_by_id(task.id) or task
        await step_merge(refreshed)


def _handle_segment_exhausted(task: ScriptSplitTask, seg, registry) -> None:
    """单段重试耗尽后暂停；不再自动重建分段计划和检查点。"""
    raise TaskPaused(
        ScriptSplitConstants.ERROR_SEGMENT_MAX_RETRIES,
        f"段 {seg.segment_index} 达到重试上限 {ScriptSplitConstants.SEGMENT_MAX_RETRIES}",
    )


def _location_internal_key(location: Dict[str, Any]) -> str:
    return str(location.get("id") or location.get("location_id") or "")


def _map_location_errors_to_segments(
    completed_segments: List[Any],
    errors: List[Dict[str, Any]],
) -> Dict[int, List[Dict[str, Any]]]:
    """按 location 来源把全量图错误精确回写到历史完成段。"""
    owners: Dict[str, set[int]] = {}
    for segment in completed_segments:
        parsed = segment.get_parsed_result() or {}
        for location in parsed.get("locations") or []:
            if not isinstance(location, dict):
                continue
            key = _location_internal_key(location)
            if key:
                owners.setdefault(key, set()).add(int(segment.segment_index))

    mapped: Dict[int, List[Dict[str, Any]]] = {}
    fallback_index = min(
        (int(segment.segment_index) for segment in completed_segments),
        default=1,
    )
    for error in errors:
        involved = {
            str(error.get("location_id") or ""),
            str(error.get("parent_id") or ""),
        }
        involved.update(
            str(value) for value in (error.get("involved_location_ids") or [])
        )
        indexes: set[int] = set()
        for location_id in involved:
            indexes.update(owners.get(location_id) or set())
        if not indexes:
            indexes.add(fallback_index)
        for segment_index in indexes:
            mapped.setdefault(segment_index, []).append(dict(error, _hard_gate=True))
    return mapped


def _map_character_errors_to_segments(
    completed_segments: List[Any],
    errors: List[Dict[str, Any]],
) -> Dict[int, List[Dict[str, Any]]]:
    """按 shot._segment_id / character_id 把合并级角色错误回写到来源段。"""
    by_segment_id: Dict[str, int] = {}
    character_owners: Dict[str, set[int]] = {}
    fallback_index = min(
        (int(segment.segment_index) for segment in completed_segments),
        default=1,
    )
    for segment in completed_segments:
        segment_index = int(segment.segment_index)
        by_segment_id[str(segment.segment_id or "")] = segment_index
        parsed = segment.get_parsed_result() or {}
        for character in parsed.get("characters") or []:
            if not isinstance(character, dict):
                continue
            character_id = str(character.get("id") or character.get("character_id") or "")
            if character_id:
                character_owners.setdefault(character_id, set()).add(segment_index)

    mapped: Dict[int, List[Dict[str, Any]]] = {}
    for error in errors:
        indexes: set[int] = set()
        segment_id = str(error.get("segment_id") or "")
        if segment_id in by_segment_id:
            indexes.add(by_segment_id[segment_id])
        character_id = str(error.get("character_id") or "")
        indexes.update(character_owners.get(character_id) or set())
        if not indexes:
            indexes.add(fallback_index)
        for segment_index in indexes:
            mapped.setdefault(segment_index, []).append(dict(error, _hard_gate=True))
    return mapped


# ---- 单步：合并与全局校验 ----

def _safe_int_or_none(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _enrich_shot_location_fields(
    merged: Dict[str, Any],
    db_locations: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """回填 shot 级场景字段（db_location_id / location_name / db_location_pic）。

    视频工作流来源不经过 storyboard 发布 bootstrap，前端只能读取 shot 级字段
    匹配世界场景（见 nodes.js syncShotFramesToShots 的 shotLocationInfo 逻辑）。
    这里按 shot.location_id → locations[].location_db_id 映射，未命中时沿
    parent_id 向上递归（对齐旧 _match_location_to_db 行为）；名称/参考图直接
    取合并阶段已加载的 DB 场景树，避免逐 shot 查库。
    """
    if not isinstance(merged, dict):
        return merged
    locations = [
        location for location in (merged.get("locations") or [])
        if isinstance(location, dict)
    ]
    if not locations:
        return merged
    location_map = {
        str(location.get("id")): location
        for location in locations
        if location.get("id") not in (None, "")
    }
    db_by_id = {
        _safe_int_or_none(location.get("id")): location
        for location in flatten_db_locations(db_locations or [])
        if _safe_int_or_none(location.get("id")) is not None
    }

    def _resolve_db_id(internal_id: Any, depth: int = 0) -> Optional[int]:
        if depth > 10:
            return None
        location = location_map.get(str(internal_id or ""))
        if not location:
            return None
        db_id = _safe_int_or_none(location.get("location_db_id"))
        if db_id is not None:
            return db_id
        return _resolve_db_id(location.get("parent_id"), depth + 1)

    for group in merged.get("shot_groups") or []:
        if not isinstance(group, dict):
            continue
        for shot in group.get("shots") or []:
            if not isinstance(shot, dict) or not shot.get("location_id"):
                continue
            db_id = _resolve_db_id(shot.get("location_id"))
            if db_id is None:
                continue
            db_row = db_by_id.get(db_id) or {}
            fallback_name = str(
                (location_map.get(str(shot.get("location_id"))) or {}).get("name") or ""
            )
            shot["db_location_id"] = db_id
            shot["location_name"] = db_row.get("name") or fallback_name
            shot["db_location_pic"] = db_row.get("reference_image") or ""
    return merged


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
    character_contract = await _ensure_task_character_contract(task, cfg)
    strategy = get_script_split_strategy(cfg.get("sequence_mode", "speed"))
    db_locations = None
    db_props: List[Dict[str, Any]] = []
    world_id = cfg.get("world_id")
    if world_id not in (None, ""):
        from model.location import LocationModel
        from model.props import PropsModel

        # 合并阶段必须重新加载当前世界的完整场景树。分段解析结果中的
        # location_db_id 已经过单段校验；若这里不给 sanitizer 数据库视图，
        # 它会把所有非空 DB id 都误判成模型编造值并清空 shot.location_id。
        db_locations = await asyncio.to_thread(
            LocationModel.get_tree_by_world,
            int(world_id),
            None,
        )
        # 道具同理：必须给 sanitizer 数据库视图与剧本原文，
        # 否则所有道具都会被误判成幻觉并清空 props/props_present。
        props_result = await asyncio.to_thread(
            PropsModel.list_by_world,
            int(world_id),
            1,
            ScriptSplitConstants.MERGE_PROPS_PAGE_SIZE,
        )
        db_props = (props_result or {}).get("data") or []
    if strategy.parallel_enabled:
        try:
            merged = strategy.repair_merged_result(
                merged,
                task.get_segment_plan() or {},
            )
        except ValueError as exc:
            raise EngineError("quality_merge_invalid", str(exc)) from exc
        # 先恢复规划阶段的全局注册表，再清理引用，避免并发段只返回实体子集时误删合法 ID。
        merged = sanitize_parsed_prop_references(merged, db_props, task.script_content or "")
        merged = sanitize_parsed_location_references(merged, db_locations)
    else:
        merged = sanitize_parsed_prop_references(merged, db_props, task.script_content or "")
        merged = sanitize_parsed_location_references(merged, db_locations)
        merged = repair_spatial_layout_continuity(merged)

    # 合并前再检规划 registry（生成中途可能被用户删除世界场景）
    plan = task.get_segment_plan() or {}
    if plan.get("compiled_registry"):
        plan_errors, locations_realigned = _planned_location_hard_errors(
            plan, db_locations or [],
        )
        if locations_realigned:
            # 父级冲突已按数据库自动对齐：回写持久化 plan 与 accepted registry
            _persist_realigned_plan_locations(task, plan)
        if plan_errors:
            logger.error(
                "task %s 合并前规划 registry L0 复检失败（资产可能已变更）: %s",
                task.id,
                [error.get("code") for error in plan_errors],
            )
            _pause_for_hard_gate(plan_errors)

    hard_structure_errors = validate_full_location_structure(
        merged,
        db_locations or [],
    )
    if hard_structure_errors:
        if any(
            error.get("code") == "new_root_location_forbidden"
            for error in hard_structure_errors
            if isinstance(error, dict)
        ):
            logger.error(
                "task %s 合并阶段仍命中 new_root_location_forbidden，"
                "说明 L0/L1 可能漏检: %s",
                task.id,
                hard_structure_errors,
            )
        errors_by_segment = _map_location_errors_to_segments(
            completed,
            hard_structure_errors,
        )
        await asyncio.to_thread(
            ScriptSplitSegmentModel.reopen_completed_for_hard_errors,
            task.id,
            errors_by_segment,
        )
        _pause_for_hard_gate(hard_structure_errors)

    merged = reorganize_shot_groups(
        merged, cfg.get("max_group_duration", 15))

    merged = renumber_global(merged)
    # 角色形象变化：清洗 LLM 变化点标记并向前传播持续状态（必须在
    # reorganize/renumber 之后按最终镜头顺序执行，见
    # docs/storyboard/script_split_character_variant.md）
    from services.script_split_character_variant_service import (
        sanitize_and_propagate_appearance_changes,
    )
    merged = sanitize_and_propagate_appearance_changes(merged)
    # 回填 shot 级场景字段（db_location_id/location_name/db_location_pic）。
    # 视频工作流来源不经过发布 bootstrap，前端只能依赖这些字段匹配世界场景。
    merged = _enrich_shot_location_fields(merged, db_locations)
    character_hard_errors = validate_segment_character_contract(
        merged,
        character_contract,
        task.get_accepted_registry(),
    )
    if character_hard_errors:
        errors_by_segment = _map_character_errors_to_segments(
            completed,
            character_hard_errors,
        )
        await asyncio.to_thread(
            ScriptSplitSegmentModel.reopen_completed_for_hard_errors,
            task.id,
            errors_by_segment,
        )
        _pause_for_character_contract(character_hard_errors)
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
    character_contract = await _ensure_task_character_contract(task, cfg)
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

    publish_character_errors = validate_segment_character_contract(
        final_result,
        character_contract,
        task.get_accepted_registry(),
    )
    if publish_character_errors:
        completed_segments = await asyncio.to_thread(
            ScriptSplitSegmentModel.get_completed,
            task.id,
        )
        errors_by_segment = _map_character_errors_to_segments(
            completed_segments,
            publish_character_errors,
        )
        await asyncio.to_thread(
            ScriptSplitSegmentModel.reopen_completed_for_hard_errors,
            task.id,
            errors_by_segment,
        )
        await asyncio.to_thread(
            ScriptSplitTaskModel.clear_final_result,
            task.id,
        )
        _pause_for_character_contract(publish_character_errors)

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
        if existing_count != expected_count:
            # 存在但不完整或有冲突：按设计文档 §15 停止发布
            raise EngineError(
                "publish_conflict",
                f"故事板已有 {existing_count} 个分镜（预期 {expected_count}），"
                f"可能存在手工分镜或发布中断残留，停止发布避免重复",
            )
        # 已全部发布：不直接 completed，先走配音对账（关闭 §2.3 的恢复漏洞）
        await _reconcile_voiceover_and_finalize(task, final_result)
        return

    # 再次检查故事板是否已有非本任务的分镜
    existing_scenes = await asyncio.to_thread(
        StoryboardSceneModel.list_by_storyboard, storyboard_id
    )
    if existing_scenes:
        raise EngineError(
            "storyboard_has_scenes",
            "故事板已存在分镜，不能重复生成",
        )

    # 角色形象变化变体生成（幂等、分 tick 推进，见
    # docs/storyboard/script_split_character_variant.md）。未全部终态时保存
    # final_result（含 plan 检查点）并保持 publishing 让出 tick，下个 worker
    # tick 从 plan 恢复继续轮询/提交；单变体失败/超时降级用主参考图。
    if bool(cfg.get(
        "enable_character_variant",
        ScriptSplitConstants.ENABLE_CHARACTER_VARIANT_DEFAULT,
    )):
        from services.script_split_character_variant_service import (
            SUMMARY_METADATA_KEY,
            build_character_variant_summary,
            ensure_character_variants,
        )
        variant_summary = await asyncio.to_thread(
            ensure_character_variants, task, final_result,
        )
        if not variant_summary.get("all_settled"):
            ScriptSplitTaskModel.save_field(task.id, final_result_json=final_result)
            ScriptSplitTaskModel.update_status(
                task.id, ScriptSplitConstants.STATUS_PUBLISHING,
                phase=ScriptSplitConstants.PHASE_CHARACTER_VARIANT,
            )
            logger.info(
                "task %s 角色形象变体生成进行中: %s", task.id, variant_summary,
            )
            return
        if int(variant_summary.get("total") or 0) > 0:
            final_result.setdefault("metadata", {})[SUMMARY_METADATA_KEY] = (
                build_character_variant_summary(final_result)
            )
            ScriptSplitTaskModel.save_field(task.id, final_result_json=final_result)
            logger.info(
                "task %s 角色形象变体生成完成: ready=%s failed=%s skipped=%s",
                task.id,
                variant_summary.get("ready"),
                variant_summary.get("failed"),
                variant_summary.get("skipped"),
            )

    # 发布前最后一道独立结构硬门禁。必须位于 bootstrap/create_scenes 之前，
    # 防止历史检查点、恢复流程或并发修改绕过合并级校验并产生非法场景资产。
    publish_db_locations = await _load_current_db_locations(cfg)
    publish_hard_errors = validate_full_location_structure(
        final_result,
        publish_db_locations,
    )
    if publish_hard_errors:
        _pause_for_hard_gate(publish_hard_errors)

    # 1. 场景资产化（location bootstrap）
    from services.storyboard_location_bootstrap_service import (
        LocationBootstrapStructureError,
        StoryboardLocationBootstrapService,
    )
    world_id = cfg.get("world_id")
    bootstrap_result = None
    if world_id:
        try:
            bootstrap_result = await asyncio.to_thread(
                StoryboardLocationBootstrapService().bootstrap,
                final_result, world_id, task.user_id,
            )
        except LocationBootstrapStructureError as exc:
            raise TaskPaused(exc.code, exc.message) from exc
        if str(cfg.get("sequence_mode") or "").strip().lower() == "quality":
            quality_strategy = get_storyboard_quality_sequence_strategy()
            await asyncio.to_thread(
                quality_strategy.prepare_location_references,
                final_result,
                bootstrap_result,
                int(world_id),
                int(task.user_id),
                str(task.auth_token or ""),
            )

    # 2. 构造 scenes_payload（携带角色形象变化变体选择，使分镜生图直接
    #     使用新形象：reference_selections → select_reference_variant_for_asset）
    from api.storyboard import build_storyboard_scenes_from_parsed_script
    from services.script_split_character_variant_service import (
        collect_ready_variant_map,
    )
    style = ""
    try:
        sb = await asyncio.to_thread(StoryboardModel.get_by_id, storyboard_id)
        if sb:
            style = sb.style or ""
    except Exception:
        pass
    scenes_payload = await asyncio.to_thread(
        build_storyboard_scenes_from_parsed_script,
        final_result, style,
        character_variants=collect_ready_variant_map(final_result),
    )

    # 3. 幂等创建分镜（带 script_split_task_id + source_shot_key）
    await asyncio.to_thread(
        StoryboardModel.create_scenes,
        storyboard_id, task.user_id, scenes_payload, task.id,
    )
    logger.info("task %s 分镜落库完成，storyboard %s 创建 %d 个分镜",
                task.id, storyboard_id, len(scenes_payload))

    # 4. 配音对账并决定是否 completed（首次发布路径）
    await _reconcile_voiceover_and_finalize(task, final_result)


async def _reconcile_voiceover_and_finalize(task: ScriptSplitTask, final_result: Dict[str, Any]) -> None:
    """对账本任务的对话配音，并据此决定拆分任务是否进入 completed。

    方案 §9。无论首次发布还是发布恢复（existing_count==expected_count）都执行：
    - remaining_count > 0：保持 publishing，下个 worker tick 继续对账（publishing
      在 claim_next_task 的 recoverable 列表内，lease 过期后会被重新领取）。
    - remaining_count == 0：写 metadata 摘要后 completed。
    - remaining 只含「仍可处理且未完成」的对白（有台词+角色、未入队/未 skip），
      无角色旁白等不可自动处理的不阻挡 completed。
    - 临时系统错误（对账抛异常）：抛 voiceover_bootstrap_failed，按现有任务重试机制处理。

    拆分任务只等待「音频任务已可靠入队」，不等待 TTS 实际生成完成（方案 §9.3）。
    """
    from config.constant import StoryboardAudioGenerateConstants
    from services.storyboard_voiceover_bootstrap_service import (
        StoryboardVoiceoverBootstrapService,
    )

    try:
        # ensure_for_split_task 的 limit 是仅关键字参数，用 partial 包成无参 callable
        # 交给 to_thread，避免位置参数个数不匹配。
        _reconcile = functools.partial(
            StoryboardVoiceoverBootstrapService().ensure_for_split_task,
            task.id, task.user_id,
            limit=StoryboardAudioGenerateConstants.AUTO_VOICEOVER_SUBMIT_BATCH_SIZE,
        )
        summary = await asyncio.to_thread(_reconcile)
    except Exception as exc:
        logger.warning(
            "task %s 配音对账异常: %s", task.id, exc, exc_info=True,
        )
        raise EngineError(
            "voiceover_bootstrap_failed",
            f"配音对账失败: {exc}",
        )

    if int(summary.get("remaining_count") or 0) > 0:
        # 还有未对账对白：保持 publishing，下个 tick 继续
        ScriptSplitTaskModel.update_status(
            task.id, ScriptSplitConstants.STATUS_PUBLISHING,
            phase="voiceover_bootstrap",
        )
        logger.info(
            "task %s 配音对账进行中，submitted=%s reused=%s skipped=%s failed=%s remaining=%s",
            task.id,
            summary.get("submitted_count"), summary.get("reused_count"),
            summary.get("skipped_count"), summary.get("failed_count"),
            summary.get("remaining_count"),
        )
        return

    # remaining == 0：写 metadata 摘要（方案 §12.1）后 completed
    # 不保存 token、声音绝对路径或完整台词。
    skip_reason_counts: Dict[str, int] = {}
    for item in (summary.get("skipped") or []):
        reason = item.get("reason") or "unknown"
        skip_reason_counts[reason] = skip_reason_counts.get(reason, 0) + 1
    final_result.setdefault("metadata", {})["voiceover_bootstrap"] = {
        "enabled": bool(summary.get("enabled")),
        "eligible": int(summary.get("eligible_count") or 0),
        "submitted": int(summary.get("submitted_count") or 0),
        "reused": int(summary.get("reused_count") or 0),
        "skipped": int(summary.get("skipped_count") or 0),
        "failed": int(summary.get("failed_count") or 0),
        "skip_reasons": skip_reason_counts,
        "completed_at": datetime.now().isoformat(),
    }
    ScriptSplitTaskModel.save_field(task.id, final_result_json=final_result)
    ScriptSplitTaskModel.update_status(
        task.id, ScriptSplitConstants.STATUS_COMPLETED,
        phase="done", progress=100,
    )
    logger.info(
        "task %s 发布完成（含配音对账），submitted=%s reused=%s skipped=%s failed=%s",
        task.id,
        summary.get("submitted_count"), summary.get("reused_count"),
        summary.get("skipped_count"), summary.get("failed_count"),
    )


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
    """单段综合校验：实体 ID 策略 + 空间引用完整性。

    假定调用方已对 parsed 执行 rewrite_segment_entity_ids（engine 在校验前统一调用）。
    """
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
    joined = " ".join(str(e.get("message") or e.get("code") or "") for e in errors)
    if (
        "planned_space_unit_location_unbound" in joined
        or ("space_unit" in joined and "关联" in joined)
    ):
        lines.append(
            "- [hint] 每个 space_unit 的 name/location_key 必须对应 entities.locations 已有项；"
            "不要写 locations 未登记的 suite 等中间层。"
        )
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
