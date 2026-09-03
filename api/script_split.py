"""
Script split task API - 任务查询、结果、恢复、取消、活跃任务查询。

见 docs/script/script_parser_incremental_split_design.md §13。
提交接口（POST /api/parse-script）仍在 server.py，改为创建任务后返回 202。
本模块提供通用任务接口，供前端轮询和页面刷新恢复。
"""
import asyncio
import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Request, Header
from fastapi.responses import JSONResponse

from api.auth_identity import (
    normalize_authorization_token,
    resolve_authorization_user_id,
)
from config.constant import ScriptSplitConstants
from model.location import LocationModel
from model.script_split_segment import ScriptSplitSegmentModel
from model.script_split_task import ScriptSplitTaskModel, _resume_hint
from services.script_split_character_contract import (
    CHARACTER_CONTRACT_CONFIG_KEY,
    build_character_contract_snapshot,
)

logger = logging.getLogger(__name__)


_PUBLIC_VALIDATION_ERROR_FIELDS = (
    "code", "severity", "message", "shot_ref", "field", "segment_id",
    "character_id", "character_db_id", "actual_name", "expected_name",
    "expected_names", "_hard_gate", "_hard_gate_type",
)


class ScriptSplitPreconditionError(ValueError):
    """剧本拆分前置校验失败（如 world 无场景 / 无参考图场景）。

    由 create_split_task 在创建任务前抛出；调用方应 catch 并返回 4xx。
    """

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"[{code}] {message}")


async def _validate_world_scene_precondition(world_id: Optional[int]) -> None:
    """前置校验：world 至少有 1 个场景，且至少有 1 个带参考图的场景。

    不满足时抛 ScriptSplitPreconditionError，由调用方返回 4xx 提示用户先补齐场景/图片，
    而非拆到一半被 location_structure_guard 暂停（new_root_location_forbidden 死锁）。
    DB 查询走 asyncio.to_thread，避免阻塞事件循环（CLAUDE.md 规则 1）。
    world_id 缺失（如 cli 来源）时跳过，保持向后兼容。
    """
    if world_id is None or world_id == "":
        return
    try:
        world_id = int(world_id)
    except (TypeError, ValueError):
        return

    total, with_image = await asyncio.gather(
        asyncio.to_thread(LocationModel.count_by_world, world_id),
        asyncio.to_thread(LocationModel.count_with_image_by_world, world_id),
    )
    if total == 0:
        raise ScriptSplitPreconditionError(
            "world_no_scene",
            "当前世界没有任何场景，请先在剧本创作页创建顶层场景（并补充参考图）后再发起拆分。",
        )
    if with_image == 0:
        raise ScriptSplitPreconditionError(
            "world_no_scene_image",
            "当前世界的场景都没有参考图，请先在剧本创作页为至少一个场景补充参考图后再发起拆分。",
        )

router = APIRouter(prefix="/api/script-split", tags=["script-split"])


async def _public_task_status(task) -> dict:
    """构造轮询状态；暂停时附带精简的当前段校验详情。"""
    data = task.to_public_status()
    if (
        task.status != ScriptSplitConstants.STATUS_PAUSED
        or getattr(task, "last_error_code", None)
        != ScriptSplitConstants.ERROR_CHARACTER_PROMPT_CONTRACT_INVALID
    ):
        return data
    segment = await asyncio.to_thread(
        ScriptSplitSegmentModel.get_first_uncompleted,
        task.id,
    )
    if segment is None:
        return data
    public_errors = []
    for error in segment.get_validation_errors()[:20]:
        if not isinstance(error, dict):
            continue
        public_errors.append({
            key: error.get(key)
            for key in _PUBLIC_VALIDATION_ERROR_FIELDS
            if error.get(key) is not None
        })
    if public_errors:
        data["validation_errors"] = public_errors
    return data


def _get_user_id_from_header(user_id_header: Optional[str]) -> Optional[int]:
    if not user_id_header:
        return None
    try:
        return int(user_id_header)
    except (ValueError, TypeError):
        return None


def _check_owner(task, user_id: Optional[int]) -> bool:
    """权限校验：用户只能查询自己的任务。"""
    if user_id is None:
        return False
    return task.user_id == user_id


async def _resolve_request_identity(
    auth_header: Optional[str],
    user_id_header: Optional[str],
):
    """Authorization 优先，失效时保留浏览器 X-User-Id 兼容路径。"""
    fallback_user_id = _get_user_id_from_header(user_id_header)
    normalized_token = normalize_authorization_token(auth_header)
    if normalized_token:
        token_user_id, token_error = await resolve_authorization_user_id(auth_header)
        if token_user_id is not None:
            return token_user_id, normalized_token, None
        if fallback_user_id is not None:
            return fallback_user_id, None, None
        return None, None, token_error

    if fallback_user_id is not None:
        return fallback_user_id, None, None

    _user_id, missing_error = await resolve_authorization_user_id(None)
    return None, None, missing_error


@router.get('/tasks/{task_id}')
async def get_task_status(
    task_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """获取任务轻量状态（轮询用）。"""
    uid, _normalized_token, auth_error = await _resolve_request_identity(auth_token, user_id)
    if auth_error:
        return auth_error
    task = await _get_task_async(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"code": -1, "message": "任务不存在"})
    if not _check_owner(task, uid):
        return JSONResponse(status_code=403, content={"code": -1, "message": "无权访问该任务"})
    return {"code": 0, "data": await _public_task_status(task)}


@router.get('/tasks/{task_id}/result')
async def get_task_result(
    task_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """获取最终合并结果（仅 completed 状态可取）。"""
    uid, _normalized_token, auth_error = await _resolve_request_identity(auth_token, user_id)
    if auth_error:
        return auth_error
    task = await _get_task_async(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"code": -1, "message": "任务不存在"})
    if not _check_owner(task, uid):
        return JSONResponse(status_code=403, content={"code": -1, "message": "无权访问该任务"})
    if task.status != ScriptSplitConstants.STATUS_COMPLETED:
        return JSONResponse(
            status_code=409,
            content={"code": -1, "message": f"任务尚未完成，当前状态: {task.status}"},
        )
    final = task.get_final_result()
    return {"code": 0, "data": final}


@router.get('/active-task')
async def get_active_task(
    request: Request,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """按来源查找最近活跃任务，供页面刷新恢复。

    查询参数：source_type, source_id, source_node_key(可选)
    """
    import asyncio
    uid, _normalized_token, auth_error = await _resolve_request_identity(auth_token, user_id)
    if auth_error:
        return auth_error
    source_type = request.query_params.get('source_type')
    source_id_raw = request.query_params.get('source_id')
    source_node_key = request.query_params.get('source_node_key')

    if not source_type or not source_id_raw:
        return JSONResponse(
            status_code=400,
            content={"code": -1, "message": "缺少 source_type 或 source_id"},
        )
    try:
        source_id = int(source_id_raw)
    except (ValueError, TypeError):
        return JSONResponse(
            status_code=400,
            content={"code": -1, "message": "source_id 必须是整数"},
        )

    task = await asyncio.to_thread(
        ScriptSplitTaskModel.get_active_by_source,
        source_type, source_id, source_node_key,
    )
    if not task:
        return {"code": 0, "data": None}
    if not _check_owner(task, uid):
        return {"code": 0, "data": None}
    return {"code": 0, "data": await _public_task_status(task)}


def _resume_target_state(task) -> str:
    """根据持久化检查点选择恢复阶段，避免已有计划重新卡回 planning。"""
    if task.phase == "publishing" or task.get_final_result():
        return ScriptSplitConstants.STATUS_PUBLISHING
    if task.get_segment_plan():
        return ScriptSplitConstants.STATUS_GENERATING
    return ScriptSplitConstants.STATUS_QUEUED


async def _resume_task_from_checkpoint(task, auth_token: Optional[str] = None) -> str:
    """从持久化检查点恢复任务，并刷新当前请求携带的鉴权信息。"""
    import asyncio

    target_status = _resume_target_state(task)
    target_phase = {
        ScriptSplitConstants.STATUS_PUBLISHING: "publishing",
        ScriptSplitConstants.STATUS_GENERATING: "segment_generation",
        ScriptSplitConstants.STATUS_QUEUED: "queued",
    }[target_status]
    target_progress = {
        ScriptSplitConstants.STATUS_PUBLISHING: max(task.progress or 0, 95),
        ScriptSplitConstants.STATUS_GENERATING: max(task.progress or 0, 10),
        ScriptSplitConstants.STATUS_QUEUED: 5,
    }[target_status]

    # paused 通常表示上一重试周期已经耗尽。用户显式恢复时重置当前未完成段的
    # 周期计数，再让根任务进入可领取状态；但已有完整候选的耗尽任务必须保留
    # 计数，供新版引擎在下一 tick 直接强制接纳，避免再调用 LLM。
    preserve_exhausted_budget = (
        getattr(task, "last_error_code", None)
        == ScriptSplitConstants.ERROR_SEGMENT_QC_FAILED
    )
    if (
        getattr(task, "last_error_code", None)
        == ScriptSplitConstants.ERROR_SEGMENT_MAX_RETRIES
        and target_status == ScriptSplitConstants.STATUS_GENERATING
    ):
        current_segment = await asyncio.to_thread(
            ScriptSplitSegmentModel.get_first_uncompleted,
            task.id,
        )
        preserve_exhausted_budget = bool(
            current_segment
            and current_segment.get_parsed_result() is not None
        )
    if (
        task.status == ScriptSplitConstants.STATUS_PAUSED
        and target_status == ScriptSplitConstants.STATUS_GENERATING
        and not preserve_exhausted_budget
    ):
        await asyncio.to_thread(
            ScriptSplitSegmentModel.reset_retry_budget,
            task.id,
        )

    if auth_token:
        await asyncio.to_thread(
            ScriptSplitTaskModel.save_field,
            task.id,
            auth_token=auth_token,
        )
    await asyncio.to_thread(
        ScriptSplitTaskModel.update_status,
        task.id,
        target_status,
        phase=target_phase,
        progress=target_progress,
        clear_error=True,
    )
    return target_status


@router.post('/tasks/{task_id}/resume')
async def resume_task(
    task_id: int,
    request: Request,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """恢复 paused / waiting_auth 任务。

    - waiting_auth：用当前请求的新 token 更新后，从持久化检查点继续。
    - paused：发布阶段恢复 publishing，已有计划恢复 generating，否则恢复 queued。

    拦截门：当 ``last_error_code`` 属于外部依赖/硬门禁类（RESUME_BLOCKED_ERROR_CODES）
    时，盲目重跑必然再次 paused（根因未清除）。此时默认拒绝，要求调用方传 ``force:true``
    确认根因已排除后再重试；waiting_auth 必须带新 Authorization（auth_token）。
    拦截不改 DB 状态，任务仍停在 paused，Agent 可读 error_code/resume_hint 决策。
    """
    uid, normalized_token, auth_error = await _resolve_request_identity(auth_token, user_id)
    if auth_error:
        return auth_error
    task = await _get_task_async(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"code": -1, "message": "任务不存在"})
    if not _check_owner(task, uid):
        return JSONResponse(status_code=403, content={"code": -1, "message": "无权访问该任务"})

    if task.status not in (ScriptSplitConstants.STATUS_PAUSED,
                           ScriptSplitConstants.STATUS_WAITING_AUTH):
        return JSONResponse(
            status_code=409,
            content={"code": -1, "message": f"任务当前状态 {task.status} 不可恢复"},
        )

    # 解析 body：允许空 body（兼容旧前端），force=true 时跳过拦截门
    try:
        body = await request.json()
    except Exception:
        body = {}
    force = bool(isinstance(body, dict) and body.get("force"))

    err = getattr(task, "last_error_code", None)
    hint = _resume_hint(task.status, err)
    if not force and err in ScriptSplitConstants.RESUME_BLOCKED_ERROR_CODES:
        return JSONResponse(
            status_code=409,
            content={
                "code": -1,
                "message": f"任务暂停根因是 {err}，根因在外部依赖/硬门禁，需排查后传 force:true 重试",
                "error_code": err,
                "error_message": getattr(task, "last_error_message", None),
                "resume_hint": hint,
            },
        )
    if err in ScriptSplitConstants.RESUME_NEEDS_AUTH_ERROR_CODES and not normalized_token:
        return JSONResponse(
            status_code=409,
            content={
                "code": -1,
                "message": "鉴权失效，请在 /api/agent-auth/exchange 重新换取 auth_token 后带 Authorization 头调用本接口",
                "error_code": err,
                "resume_hint": hint,
            },
        )

    target_status = await _resume_task_from_checkpoint(task, normalized_token)
    return {
        "code": 0,
        "message": "任务已恢复",
        "data": {"task_id": task_id, "status": target_status},
    }


@router.post('/tasks/{task_id}/cancel')
async def cancel_task(
    task_id: int,
    auth_token: Optional[str] = Header(None, alias="Authorization"),
    user_id: Optional[int] = Header(None, alias="X-User-Id"),
):
    """协作式取消：只置 cancel_requested 标记，不强杀线程。

    worker 在段间检查点生效；当前 LLM 调用结束后丢弃响应进入 cancelled。
    """
    import asyncio
    uid, _normalized_token, auth_error = await _resolve_request_identity(auth_token, user_id)
    if auth_error:
        return auth_error
    task = await _get_task_async(task_id)
    if not task:
        return JSONResponse(status_code=404, content={"code": -1, "message": "任务不存在"})
    if not _check_owner(task, uid):
        return JSONResponse(status_code=403, content={"code": -1, "message": "无权访问该任务"})

    if task.status in ScriptSplitConstants.TERMINAL_STATUSES:
        return JSONResponse(
            status_code=409,
            content={"code": -1, "message": f"任务已处于终态 {task.status}"},
        )

    await asyncio.to_thread(ScriptSplitTaskModel.request_cancel, task_id)
    # 若当前在 LLM 调用中，状态转为 cancelling；否则 worker 下个检查点直接转 cancelled
    if task.status != ScriptSplitConstants.STATUS_CANCELLING:
        await asyncio.to_thread(
            ScriptSplitTaskModel.update_status,
            task_id, ScriptSplitConstants.STATUS_CANCELLING,
        )
    return {"code": 0, "message": "取消请求已提交", "data": {"task_id": task_id, "status": "cancelling"}}


async def _get_task_async(task_id: int):
    """用 asyncio.to_thread 包装同步 DB 访问（AGENTS.md 第1条）。"""
    import asyncio
    return await asyncio.to_thread(ScriptSplitTaskModel.get_by_id, task_id)


# ---- 任务创建辅助（供 server.py / storyboard.py 复用）----

def compute_active_key(user_id: int, source_type: str, source_id: Optional[int],
                       source_node_key: Optional[str], script_sha256: str,
                       config: dict) -> str:
    """生成幂等键：user+source+script_sha256+config 摘要。"""
    import json as _json
    config_sig = _json.dumps(config, sort_keys=True, ensure_ascii=False)
    raw = f"{user_id}|{source_type}|{source_id or ''}|{source_node_key or ''}|{script_sha256}|{config_sig}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:64]


def _normalize_request_config(request_config: dict) -> dict:
    """规范化 request_config，确保关键字段类型正确。

    model 字段前端有时传成对象（{name, model, model_id, vendor_id}）而非字符串，
    会导致 Gemini 路由把 dict 序列化进 URL 触发 404。这里统一拍平为字符串。
    必须在 compute_active_key 之前调用，否则 model 是 dict 还是 str 会让 active_key 漂移，
    破坏幂等。
    """
    cfg = dict(request_config or {})
    model = cfg.get("model")
    if isinstance(model, dict):
        cfg["model"] = model.get("model") or model.get("name") or ""
    elif model is not None and not isinstance(model, str):
        cfg["model"] = str(model)
    # 缺省与故事板前端一致：balanced（速度/均衡共用标准策略，quality 为企业效果模式）
    sequence_mode = str(cfg.get("sequence_mode") or "balanced").strip().lower()
    if sequence_mode not in {"speed", "balanced", "quality"}:
        raise ValueError(f"invalid sequence_mode: {sequence_mode}")
    cfg["sequence_mode"] = sequence_mode
    # 角色形象变化变体开关统一为 bool（缺省用服务端常量），避免 active_key
    # 因 "true"/True 漂移
    variant_value = cfg.get("enable_character_variant")
    if variant_value is None:
        cfg["enable_character_variant"] = bool(
            ScriptSplitConstants.ENABLE_CHARACTER_VARIANT_DEFAULT
        )
    elif isinstance(variant_value, str):
        cfg["enable_character_variant"] = variant_value.strip().lower() in ("1", "true", "yes", "on")
    else:
        cfg["enable_character_variant"] = bool(variant_value)
    return cfg


async def create_split_task(
    user_id: int,
    source_type: str,
    source_id: Optional[int],
    source_node_key: Optional[str],
    script_content: str,
    request_config: dict,
    auth_token: Optional[str] = None,
):
    """幂等创建剧本拆分任务。

    供 POST /api/parse-script 和 POST /api/storyboard/{id}/generate-from-script 复用。
    重复提交相同任务（相同 active_key）时返回已有任务。
    Returns: (task_id, is_new)
    """
    import asyncio
    request_config = _normalize_request_config(request_config)
    # 内部角色契约只允许服务端生成；在前置校验和幂等键计算前丢弃客户端同名字段。
    request_config.pop(CHARACTER_CONTRACT_CONFIG_KEY, None)
    # 前置校验：world 必须有可用场景资产，否则不创建任务，直接提示用户补齐
    await _validate_world_scene_precondition(request_config.get("world_id"))
    script_sha256 = hashlib.sha256(
        (script_content or "").encode("utf-8")
    ).hexdigest()
    active_key = compute_active_key(
        user_id, source_type, source_id, source_node_key, script_sha256, request_config
    )
    # active_key 只描述用户请求参数；角色库快照是服务端真值。
    # 先计算幂等键再注入快照，角色在任务运行期间改名也不会让同一活跃任务漂移。
    request_config[CHARACTER_CONTRACT_CONFIG_KEY] = await asyncio.to_thread(
        build_character_contract_snapshot,
        request_config.get("world_id"),
    )
    task_id, is_new = await asyncio.to_thread(
        ScriptSplitTaskModel.create_or_get_active,
        user_id, source_type, source_id, source_node_key, active_key,
        script_sha256, script_content, request_config, auth_token,
    )
    if not is_new:
        task = await asyncio.to_thread(ScriptSplitTaskModel.get_by_id, task_id)
        if task and task.status in (
            ScriptSplitConstants.STATUS_PAUSED,
            ScriptSplitConstants.STATUS_WAITING_AUTH,
        ):
            await _resume_task_from_checkpoint(task, auth_token)
    return task_id, is_new


__all__ = ["router", "create_split_task", "compute_active_key", "ScriptSplitPreconditionError"]
