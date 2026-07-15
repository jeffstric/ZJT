"""
Script split task API - 任务查询、结果、恢复、取消、活跃任务查询。

见 docs/script/script_parser_incremental_split_design.md §13。
提交接口（POST /api/parse-script）仍在 server.py，改为创建任务后返回 202。
本模块提供通用任务接口，供前端轮询和页面刷新恢复。
"""
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
from model.script_split_segment import ScriptSplitSegmentModel
from model.script_split_task import ScriptSplitTaskModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/script-split", tags=["script-split"])


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
    return {"code": 0, "data": task.to_public_status()}


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
    return {"code": 0, "data": task.to_public_status()}


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
    # 周期计数，再让根任务进入可领取状态；但旧版 segment_qc_failed 必须保留
    # 已耗尽的 QC 轮数，供新版引擎直接强制接纳最后一个合法候选，避免再调用 LLM。
    if (
        task.status == ScriptSplitConstants.STATUS_PAUSED
        and target_status == ScriptSplitConstants.STATUS_GENERATING
        and getattr(task, "last_error_code", None)
        != ScriptSplitConstants.ERROR_SEGMENT_QC_FAILED
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
    sequence_mode = str(cfg.get("sequence_mode") or "speed").strip().lower()
    if sequence_mode not in {"speed", "balanced", "quality"}:
        raise ValueError(f"invalid sequence_mode: {sequence_mode}")
    cfg["sequence_mode"] = sequence_mode
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
    script_sha256 = hashlib.sha256(
        (script_content or "").encode("utf-8")
    ).hexdigest()
    active_key = compute_active_key(
        user_id, source_type, source_id, source_node_key, script_sha256, request_config
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


__all__ = ["router", "create_split_task", "compute_active_key"]
