"""用户模块固定 HTTP 网关。路由本身不加载任何用户代码。"""

from __future__ import annotations

import asyncio
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from config.constant import (
    USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
    USER_MODULE_MAX_PREFER_WAIT_SECONDS,
    USER_MODULE_MAX_RPC_MESSAGE_BYTES,
)
from module_runtime.protocol import MediaKind, MediaRef
from services.user_module_service import (
    UserModuleServiceError,
    get_user_module_service,
    module_job_to_dict,
)


router = APIRouter(prefix="/api/modules", tags=["user-modules"])
_background_tasks: set[asyncio.Task] = set()


class MediaJobCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    media_kind: MediaKind
    prompt: Optional[str] = Field(default=None, max_length=100000)
    inputs: List[MediaRef] = Field(default_factory=list, max_length=32)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    idempotency_key: Optional[str] = Field(default=None, min_length=8, max_length=128)


async def _resolve_requester_id(authorization: Optional[str]):
    from api.auth_identity import resolve_authorization_user_id

    try:
        return await asyncio.wait_for(
            resolve_authorization_user_id(authorization),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
    finally:
        pass


def _error_response(exc: UserModuleServiceError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error_code": exc.code, "error": str(exc)},
    )


def _prefer_wait_seconds(prefer: Optional[str]) -> float:
    if not prefer:
        return 0
    match = re.search(r"(?:^|[,;\s])wait=(\d+(?:\.\d+)?)", prefer.lower())
    if not match:
        return 0
    return min(float(match.group(1)), USER_MODULE_MAX_PREFER_WAIT_SECONDS)


def _track_background_task(task: asyncio.Task) -> None:
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


@router.post("/callbacks/{callback_token}")
async def handle_module_callback(
    callback_token: str,
    request: Request,
):
    """供应商公开回调入口；按任务签名的不可预测令牌替代登录鉴权。"""

    try:
        if len(callback_token) > 128:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error_code": "CALLBACK_NOT_FOUND", "error": "回调令牌无效"},
            )
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > USER_MODULE_MAX_RPC_MESSAGE_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"success": False, "error_code": "CALLBACK_TOO_LARGE", "error": "回调请求体过大"},
                    )
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"success": False, "error_code": "INVALID_CALLBACK", "error": "Content-Length 无效"},
                )
        raw_body = await asyncio.wait_for(
            request.body(),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        if len(raw_body) > USER_MODULE_MAX_RPC_MESSAGE_BYTES:
            return JSONResponse(
                status_code=413,
                content={"success": False, "error_code": "CALLBACK_TOO_LARGE", "error": "回调请求体过大"},
            )
        if not raw_body:
            payload = {}
        else:
            import json

            payload = json.loads(raw_body.decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("回调 JSON 必须是对象")
        job = await get_user_module_service().handle_callback(
            callback_token,
            headers={key: value for key, value in request.headers.items()},
            payload=payload,
        )
        return {"success": True, "data": {"job_id": job.job_id, "status": job.status}}
    except UserModuleServiceError as exc:
        return _error_response(exc)
    except (UnicodeDecodeError, ValueError) as exc:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error_code": "INVALID_CALLBACK", "error": str(exc)},
        )


@router.get("/{module_id}/manifest")
async def get_module_manifest(
    module_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    _user_id, auth_error = await _resolve_requester_id(authorization)
    if auth_error:
        return auth_error
    try:
        manifest = await get_user_module_service().get_active_manifest(module_id)
        public_manifest = manifest.model_dump(mode="json")
        public_manifest["permissions"]["secret_names"] = []
        return {"success": True, "data": public_manifest}
    except UserModuleServiceError as exc:
        return _error_response(exc)


@router.post("/{module_id}/media/{operation}/jobs")
async def create_media_job(
    module_id: str,
    operation: str,
    body: MediaJobCreateRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
    idempotency_header: Optional[str] = Header(default=None, alias="Idempotency-Key"),
    prefer: Optional[str] = Header(default=None, alias="Prefer"),
):
    user_id, auth_error = await _resolve_requester_id(authorization)
    if auth_error:
        return auth_error
    idempotency_key = body.idempotency_key or idempotency_header or str(uuid.uuid4())
    if not 8 <= len(idempotency_key) <= 128:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error_code": "INVALID_IDEMPOTENCY_KEY",
                "error": "Idempotency-Key 长度必须为 8 到 128 个字符",
            },
        )
    try:
        service = get_user_module_service()
        job = await service.create_media_job(
            module_id=module_id,
            requester_id=str(user_id),
            operation=operation,
            media_kind=body.media_kind,
            prompt=body.prompt,
            inputs=body.inputs,
            parameters=body.parameters,
            idempotency_key=idempotency_key,
        )
        dispatch = asyncio.create_task(service.dispatch_job(job.job_id))
        _track_background_task(dispatch)
        wait_seconds = _prefer_wait_seconds(prefer)
        if wait_seconds > 0:
            try:
                await asyncio.wait_for(asyncio.shield(dispatch), timeout=wait_seconds)
            except asyncio.TimeoutError:
                pass
            current = await service.get_job(job.job_id, str(user_id))
            status_code = 200 if current.status in {"succeeded", "failed", "cancelled", "timed_out"} else 202
            return JSONResponse(
                status_code=status_code,
                content={"success": True, "data": module_job_to_dict(current)},
            )
        return JSONResponse(
            status_code=202,
            content={"success": True, "data": module_job_to_dict(job)},
        )
    except UserModuleServiceError as exc:
        return _error_response(exc)


@router.get("/{module_id}/jobs/{job_id}")
async def get_media_job(
    module_id: str,
    job_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    user_id, auth_error = await _resolve_requester_id(authorization)
    if auth_error:
        return auth_error
    try:
        job = await get_user_module_service().get_job(job_id, str(user_id))
        if job.module_id != module_id:
            raise UserModuleServiceError("JOB_NOT_FOUND", "模块任务不存在", status_code=404)
        return {"success": True, "data": module_job_to_dict(job)}
    except UserModuleServiceError as exc:
        return _error_response(exc)


@router.delete("/{module_id}/jobs/{job_id}")
async def cancel_media_job(
    module_id: str,
    job_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    user_id, auth_error = await _resolve_requester_id(authorization)
    if auth_error:
        return auth_error
    try:
        service = get_user_module_service()
        existing = await service.get_job(job_id, str(user_id))
        if existing.module_id != module_id:
            raise UserModuleServiceError("JOB_NOT_FOUND", "模块任务不存在", status_code=404)
        job = await service.cancel_job(job_id, str(user_id))
        return {"success": True, "data": module_job_to_dict(job)}
    except UserModuleServiceError as exc:
        return _error_response(exc)
