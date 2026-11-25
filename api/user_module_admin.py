"""用户模块生成、审批、激活和回滚管理接口。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Header, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from config.constant import (
    USER_MODULE_COMFYUI_CONNECTOR,
    USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
    USER_MODULE_GENERATION_MAX_FILE_BYTES,
    USER_MODULE_HTTP_CONNECTOR,
    USER_MODULE_REQUIREMENT_MAX_LENGTH,
    USER_MODULE_REVIEW_ENABLED,
    USER_MODULE_REVIEW_MODEL,
    USER_MODULE_REVIEW_MODEL_ID,
    USER_MODULE_REVIEW_POLICY_VERSION,
    USER_MODULE_REVIEW_REQUIRED,
    USER_MODULE_REVIEW_VENDOR_ID,
)
from config.version import get_app_version
import logging

logger = logging.getLogger(__name__)

from module_runtime.client import (
    SupervisorClient,
    SupervisorClientError,
    sanitize_release_validation_error,
)
from module_runtime.compatibility import load_core_abi
from module_runtime.generation import AsyncGenerationService, UserModuleReviewBusyError
from module_runtime.health_security import sanitize_health_details
from services.user_module_agent_service import (
    UserModuleAgentAnswerError,
    UserModuleAgentBusyError,
    UserModuleAgentCreateError,
    UserModuleAgentTaskNotFoundError,
    get_user_module_agent_service,
)


router = APIRouter(prefix="/api/admin/user-modules", tags=["user-module-admin"])
generation_service = AsyncGenerationService()


def _dedicated_review_model_configured() -> bool:
    return bool(
        str(USER_MODULE_REVIEW_MODEL or "").strip()
        and int(USER_MODULE_REVIEW_MODEL_ID or 0) > 0
        and int(USER_MODULE_REVIEW_VENDOR_ID or 0) > 0
    )


class GenerationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$")
    requirement: str = Field(min_length=10, max_length=USER_MODULE_REQUIREMENT_MAX_LENGTH)
    model_id: Optional[int] = Field(default=None, gt=0)
    vendor_id: Optional[int] = Field(default=None, gt=0)


class GenerationFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=600000)


class ModuleAgentTaskCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$")
    requirement: str = Field(default="", max_length=USER_MODULE_REQUIREMENT_MAX_LENGTH)
    model_id: int = Field(gt=0)
    vendor_id: Optional[int] = Field(default=None, gt=0)
    enable_thinking: bool = False
    thinking_effort: str = Field(default="medium", pattern=r"^(low|medium|high)$")
    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    connector: str = Field(default=USER_MODULE_HTTP_CONNECTOR, pattern=r"^(http|local_comfyui)$")
    comfyui_base_url: Optional[str] = Field(default=None, max_length=512)
    workflow_json: Optional[str] = Field(default=None, max_length=600000)
    workflow_path: Optional[str] = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def validate_connector_payload(self):
        connector = (self.connector or USER_MODULE_HTTP_CONNECTOR).strip()
        requirement = (self.requirement or "").strip()
        if connector == USER_MODULE_COMFYUI_CONNECTOR:
            if not (self.comfyui_base_url or "").strip():
                raise ValueError("本地 ComfyUI 需要填写地址")
            has_json = bool((self.workflow_json or "").strip())
            has_path = bool((self.workflow_path or "").strip())
            if not has_json and not has_path:
                raise ValueError("本地 ComfyUI 需要上传工作流 API JSON 或提供文件路径")
            if has_json and has_path:
                raise ValueError("工作流 JSON 与路径只能提供其中一项")
        elif len(requirement) < 10:
            raise ValueError("需求描述至少 10 个字符")
        self.requirement = requirement
        return self


class ModuleAgentTaskAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question_id: str = Field(min_length=3, max_length=80, pattern=r"^q_[A-Za-z0-9_]+$")
    selected: Optional[str] = Field(default=None, max_length=500)
    free_text: Optional[str] = Field(default=None, max_length=20000)

    @model_validator(mode="after")
    def require_selected_or_free_text(self):
        selected = (self.selected or "").strip() or None
        free_text = (self.free_text or "").strip() or None
        if not selected and not free_text:
            raise ValueError("必须提供 selected 或 free_text")
        self.selected = selected
        self.free_text = free_text
        return self


async def _require_admin_user(authorization: Optional[str]):
    from api.auth_identity import normalize_authorization_token
    from model.user_tokens import UserTokensModel
    from model.users import UsersModel

    token = normalize_authorization_token(authorization)
    if not token:
        return None, JSONResponse(
            status_code=401,
            content={"success": False, "error_code": "missing_auth_token", "error": "Authorization is required"},
        )
    try:
        user_id = await asyncio.wait_for(
            asyncio.to_thread(UserTokensModel.get_user_id_by_token, token),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        user = await asyncio.wait_for(
            asyncio.to_thread(UsersModel.get_by_id, user_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        ) if user_id else None
    finally:
        pass
    if not user_id or not user:
        return None, JSONResponse(
            status_code=401,
            content={"success": False, "error_code": "invalid_auth_token", "error": "Authorization is invalid or expired"},
        )
    if user.role != "admin":
        return None, JSONResponse(
            status_code=403,
            content={"success": False, "error_code": "admin_required", "error": "Administrator permission is required"},
        )
    return user, None


def _failure(exc: Exception, status_code: int = 400) -> JSONResponse:
    content = {
        "success": False,
        "error_code": getattr(exc, "code", "user_module_operation_failed"),
        "error": str(exc),
    }
    safe_details = sanitize_health_details(getattr(exc, "safe_details", None))
    if safe_details:
        content["details"] = safe_details
    return JSONResponse(
        status_code=status_code,
        content=content,
    )


async def _resolve_llm_model_route(
    *,
    model_id: int,
    vendor_id: Optional[int],
    require_tool_calling: bool,
    require_explicit_vendor: bool = False,
):
    """解析并校验服务端可信的 LLM 模型路由。"""

    from model.model import ModelModel
    from model.vendor_model import VendorModelModel

    model = await asyncio.wait_for(
        asyncio.to_thread(ModelModel.get_by_id, model_id),
        timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
    )
    model_name = str(getattr(model, "model_name", "") or "").strip()
    if not model or not model.enabled or not model_name:
        raise ValueError("LLM 模型不存在或未启用")
    if require_tool_calling and not getattr(model, "supports_tools", False):
        raise ValueError("LLM 模型不支持工具调用")

    if vendor_id is None:
        if require_explicit_vendor:
            raise ValueError("必须指定与 LLM 模型关联的供应商")
        resolved_vendor_id = await asyncio.wait_for(
            asyncio.to_thread(VendorModelModel.get_vendor_id_by_model_id, model_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
    else:
        vendor_model = await asyncio.wait_for(
            asyncio.to_thread(
                VendorModelModel.get_by_vendor_model,
                vendor_id,
                model_id,
            ),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        if vendor_model is None:
            raise ValueError("供应商与 LLM 模型未关联")
        resolved_vendor_id = vendor_id

    if not resolved_vendor_id:
        raise ValueError("LLM 模型未关联供应商")
    return model_name, int(resolved_vendor_id)


@router.post("/agent/tasks")
async def create_module_agent_task(
    body: ModuleAgentTaskCreateRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error

    from api.auth_identity import normalize_authorization_token
    token = normalize_authorization_token(authorization)
    try:
        model_name, vendor_id = await _resolve_llm_model_route(
            model_id=body.model_id,
            vendor_id=body.vendor_id,
            require_tool_calling=True,
        )
        agent_service = await asyncio.wait_for(
            asyncio.to_thread(get_user_module_agent_service),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        state = await agent_service.create_task(
            module_id=body.module_id,
            requirement=body.requirement,
            created_by=str(admin.id),
            auth_token=token,
            model=model_name,
            model_id=body.model_id,
            vendor_id=int(vendor_id),
            enable_thinking=body.enable_thinking,
            thinking_effort=body.thinking_effort,
            language=body.language,
            connector=body.connector,
            comfyui_base_url=body.comfyui_base_url,
            workflow_json=body.workflow_json,
            workflow_path=body.workflow_path,
        )
        return JSONResponse(status_code=202, content={"success": True, "data": state})
    except UserModuleAgentCreateError as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error_code": exc.code, "error": str(exc)},
        )
    except UserModuleAgentBusyError as exc:
        return JSONResponse(
            status_code=429,
            content={"success": False, "error_code": "agent_task_busy", "error": str(exc)},
        )
    except Exception as exc:
        return _failure(exc)


@router.get("/agent/tasks")
async def list_module_agent_tasks(
    limit: int = Query(default=10, ge=1, le=50),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """最近的生成任务摘要，供管理页重新打开进度弹窗（只返回当前管理员的任务）。"""
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        agent_service = await asyncio.wait_for(
            asyncio.to_thread(get_user_module_agent_service),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        tasks = await agent_service.list_tasks(limit=limit, requester_id=str(admin.id))
        return {"success": True, "data": {"tasks": tasks}}
    except Exception as exc:
        return _failure(exc)


@router.get("/agent/tasks/{task_id}")
async def get_module_agent_task(
    task_id: str,
    after_id: int = Query(default=0, ge=0),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        agent_service = await asyncio.wait_for(
            asyncio.to_thread(get_user_module_agent_service),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        state = await agent_service.get_task(
            task_id,
            requester_id=str(admin.id),
            after_id=after_id,
        )
        return {"success": True, "data": state}
    except UserModuleAgentTaskNotFoundError as exc:
        return _failure(exc, 404)
    except Exception as exc:
        return _failure(exc)


@router.post("/agent/tasks/{task_id}/answers")
async def submit_module_agent_task_answer(
    task_id: str,
    body: ModuleAgentTaskAnswerRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        agent_service = await asyncio.wait_for(
            asyncio.to_thread(get_user_module_agent_service),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        data = await agent_service.submit_answer(
            task_id,
            requester_id=str(admin.id),
            question_id=body.question_id,
            selected=body.selected,
            free_text=body.free_text,
        )
        return {"success": True, "data": data}
    except UserModuleAgentTaskNotFoundError as exc:
        return _failure(exc, 404)
    except UserModuleAgentAnswerError as exc:
        return _failure(exc, exc.status_code)
    except Exception as exc:
        return _failure(exc)


@router.post("/agent/tasks/{task_id}/cancel")
async def cancel_module_agent_task(
    task_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """管理员停止生成：协作式取消，任务立即置为 cancelled 终态（幂等）。"""
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        agent_service = await asyncio.wait_for(
            asyncio.to_thread(get_user_module_agent_service),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        state = await agent_service.cancel_task(task_id, requester_id=str(admin.id))
        return {"success": True, "data": state}
    except UserModuleAgentTaskNotFoundError as exc:
        return _failure(exc, 404)
    except Exception as exc:
        return _failure(exc)


def _datetime_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


@router.get("/secret-catalog")
async def get_secret_catalog(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """模块可授权密钥目录：名称/描述/是否已配置，绝不返回密钥值。"""

    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from config.default_configs import DEFAULT_CONFIGS
    from module_runtime.secret_resolver import (
        read_dynamic_secret,
        user_module_grantable_aliases,
    )

    descriptions = {
        entry["key"]: entry.get("description", "")
        for entry in DEFAULT_CONFIGS
        if isinstance(entry, dict) and entry.get("user_module_grantable")
    }
    catalog = []
    for secret_name, config_path in sorted(user_module_grantable_aliases().items()):
        config_key = ".".join(config_path)
        try:
            value = await asyncio.wait_for(
                asyncio.to_thread(read_dynamic_secret, config_path),
                timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
            )
            configured = isinstance(value, str) and bool(value.strip())
        except Exception:
            configured = False
        catalog.append(
            {
                "secret_name": secret_name,
                "config_key": config_key,
                "description": descriptions.get(config_key, ""),
                "configured": configured,
            }
        )
    return {"success": True, "data": {"catalog": catalog}}


@router.get("/runtime")
async def get_module_runtime(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """返回后台页所需的核心版本、ABI 与 Supervisor 健康摘要。"""

    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    core_version, abi = await asyncio.gather(
        asyncio.wait_for(
            asyncio.to_thread(get_app_version),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        ),
        asyncio.wait_for(
            asyncio.to_thread(load_core_abi),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        ),
    )
    supervisor = {"healthy": False, "runner_count": 0}
    try:
        supervisor.update(await SupervisorClient().health())
    except SupervisorClientError as exc:
        supervisor["error_code"] = exc.code
        supervisor["error"] = str(exc)
    return {
        "success": True,
        "data": {
            "core_version": core_version,
            "abi": {**abi, "core_version": core_version},
            "abi_declared_core_version": abi.get("core_version"),
            "supervisor": supervisor,
            "review": {
                "enabled": bool(USER_MODULE_REVIEW_ENABLED),
                "required": bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                "dedicated_model_configured": _dedicated_review_model_configured(),
                "fallback": "generation_model",
                "policy_version": USER_MODULE_REVIEW_POLICY_VERSION,
            },
        },
    }


@router.get("/modules")
async def list_modules(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from model.user_modules import UserModulesModel

    try:
        modules = await asyncio.wait_for(
            asyncio.to_thread(UserModulesModel.list_modules),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        return {
            "success": True,
            "data": [
                {
                    "id": module.id,
                    "module_id": module.module_id,
                    "name": module.name,
                    "enabled": module.enabled,
                    "status": module.status,
                    "active_release_id": module.active_release_id,
                    "active_version": module.active_version,
                    "active_code_digest": module.active_code_digest,
                    "active_release_status": module.active_release_status,
                    "active_manifest": module.active_manifest,
                    "release_count": module.release_count,
                    "last_error": module.last_error,
                    "create_at": _datetime_value(module.create_at),
                    "update_at": _datetime_value(module.update_at),
                }
                for module in modules
            ],
        }
    except Exception as exc:
        return _failure(exc, 503)


@router.get("")
async def get_user_module_overview(
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """管理页首屏聚合接口，减少三次网络往返。"""

    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from model.user_modules import UserModulesModel

    try:
        modules, generations, core_version, abi = await asyncio.gather(
            asyncio.wait_for(
                asyncio.to_thread(UserModulesModel.list_modules),
                timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
            ),
            generation_service.list_generations(created_by=str(admin.id), limit=100),
            asyncio.wait_for(
                asyncio.to_thread(get_app_version),
                timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
            ),
            asyncio.wait_for(
                asyncio.to_thread(load_core_abi),
                timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
            ),
        )
        module_payload = [
            {
                "id": module.id,
                "module_id": module.module_id,
                "name": module.name,
                "enabled": module.enabled,
                "status": module.status,
                "active_release_id": module.active_release_id,
                "active_version": module.active_version,
                "active_code_digest": module.active_code_digest,
                "active_release_status": module.active_release_status,
                "active_manifest": module.active_manifest,
                "release_count": module.release_count,
                "last_error": module.last_error,
                "create_at": _datetime_value(module.create_at),
                "update_at": _datetime_value(module.update_at),
            }
            for module in modules
        ]
        return {
            "success": True,
            "data": {
                "modules": module_payload,
                "generations": generations,
                "runtime": {
                    "core_version": core_version,
                    "abi": abi,
                    "review": {
                        "enabled": bool(USER_MODULE_REVIEW_ENABLED),
                        "required": bool(USER_MODULE_REVIEW_ENABLED and USER_MODULE_REVIEW_REQUIRED),
                        "dedicated_model_configured": _dedicated_review_model_configured(),
                        "fallback": "generation_model",
                        "policy_version": USER_MODULE_REVIEW_POLICY_VERSION,
                    },
                },
            },
        }
    except Exception as exc:
        return _failure(exc, 503)


@router.post("/generations")
async def create_generation(
    body: GenerationCreateRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        review_target_required = bool(
            USER_MODULE_REVIEW_ENABLED
            and USER_MODULE_REVIEW_REQUIRED
            and not _dedicated_review_model_configured()
        )
        if (body.model_id is None) != (body.vendor_id is None):
            raise ValueError("model_id 与 vendor_id 必须同时提供")
        if review_target_required and body.model_id is None:
            raise ValueError("未配置独立审核模型时，必须提供 model_id 与 vendor_id")

        create_kwargs = {
            "module_id": body.module_id,
            "requirement": body.requirement,
            "created_by": str(admin.id),
        }
        if body.model_id is not None:
            model_name, vendor_id = await _resolve_llm_model_route(
                model_id=body.model_id,
                vendor_id=body.vendor_id,
                require_tool_calling=False,
                require_explicit_vendor=True,
            )
            create_kwargs.update(
                review_model=model_name,
                review_model_id=body.model_id,
                review_vendor_id=vendor_id,
            )
        state = await generation_service.create(
            **create_kwargs,
        )
        return JSONResponse(status_code=201, content={"success": True, "data": state})
    except Exception as exc:
        return _failure(exc)


@router.get("/generations")
async def list_generations(
    module_id: Optional[str] = Query(default=None, min_length=3, max_length=128),
    status: Optional[str] = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=100, ge=1, le=200),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        states = await generation_service.list_generations(
            module_id=module_id,
            status=status,
            created_by=str(admin.id),
            limit=limit,
        )
        return {"success": True, "data": states}
    except Exception as exc:
        return _failure(exc, 503)


@router.get("/generations/{generation_id}")
async def get_generation(
    generation_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        await generation_service.assert_owner(generation_id, str(admin.id))
        state, files = await asyncio.gather(
            generation_service.get(generation_id),
            generation_service.list_files(generation_id),
        )
        return {"success": True, "data": {**state, "files": files}}
    except Exception as exc:
        return _failure(exc, 404)


@router.put("/generations/{generation_id}/files")
async def write_generation_file(
    generation_id: str,
    body: GenerationFileRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        await generation_service.assert_owner(generation_id, str(admin.id))
        result = await generation_service.write_file(generation_id, body.path, body.content)
        return {"success": True, "data": result}
    except Exception as exc:
        return _failure(exc)


@router.get("/generations/{generation_id}/files/content")
async def read_generation_file(
    generation_id: str,
    path: str = Query(min_length=1, max_length=512),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        await generation_service.assert_owner(generation_id, str(admin.id))
        result = await generation_service.read_file(generation_id, path)
        return {"success": True, "data": result}
    except Exception as exc:
        return _failure(exc, 404)


@router.get("/project-code/search")
async def search_project_code(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        result = await generation_service.search_project(q, limit)
        return {"success": True, "data": result}
    except Exception as exc:
        return _failure(exc)


@router.get("/project-code/file")
async def read_project_code_file(
    path: str = Query(min_length=1, max_length=512),
    start_line: int = Query(default=1, ge=1),
    end_line: int = Query(default=400, ge=1),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        result = await generation_service.read_project_file(path, start_line, end_line)
        return {"success": True, "data": result}
    except Exception as exc:
        return _failure(exc)


@router.post("/generations/{generation_id}/validate")
async def validate_generation(
    generation_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        await generation_service.assert_owner(generation_id, str(admin.id))
        from api.auth_identity import normalize_authorization_token

        result = await generation_service.validate(
            generation_id,
            auth_token=normalize_authorization_token(authorization),
        )
        status_code = 200 if result["ok"] else 422
        return JSONResponse(status_code=status_code, content={"success": result["ok"], "data": result})
    except UserModuleReviewBusyError as exc:
        return JSONResponse(
            status_code=409,
            content={
                "success": False,
                "error_code": "review_in_progress",
                "error": str(exc),
            },
        )
    except Exception as exc:
        return _failure(exc)


@router.post("/generations/{generation_id}/approve")
async def approve_generation(
    generation_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        await generation_service.assert_owner(generation_id, str(admin.id))
        state = await generation_service.approve(generation_id, str(admin.id))
        return {"success": True, "data": state}
    except SupervisorClientError as exc:
        safe_exc = sanitize_release_validation_error(exc)
        return _failure(safe_exc, safe_exc.status_code)
    except Exception as exc:
        return _failure(exc)


@router.get("/{module_id}/releases")
async def list_module_releases(
    module_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from model.user_modules import UserModulesModel

    releases = await asyncio.wait_for(
        asyncio.to_thread(UserModulesModel.list_releases, module_id),
        timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
    )
    return {
        "success": True,
        "data": [
            {
                "id": release.id,
                "module_id": release.module_id,
                "version": release.version,
                "code_digest": release.code_digest,
                "status": release.status,
                "compatibility_status": release.compatibility_status,
                "last_error": release.last_error,
            }
            for release in releases
        ],
    }


async def _resolve_release_dir(module_id: str, release_id: int):
    """校验 Release 归属并定位其目录（兼容相对/绝对两种 release_path 存储形式）。"""
    from model.user_modules import UserModulesModel
    from module_runtime.paths import get_user_module_root, resolve_within_root

    release = await asyncio.wait_for(
        asyncio.to_thread(UserModulesModel.get_release, release_id),
        timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
    )
    if not release or release.module_id != module_id:
        raise ValueError("Release 不存在或不属于该模块")
    module_root = get_user_module_root()
    configured = Path(release.release_path)
    if configured.is_absolute():
        resolved = configured.resolve(strict=True)
        try:
            resolved.relative_to(module_root)
        except ValueError as exc:
            raise ValueError("Release 路径不在用户模块根目录内") from exc
        return release, resolved
    release_dir = resolve_within_root(module_root, *configured.parts, must_exist=True)
    return release, release_dir


def _list_release_files_sync(release_dir: Path):
    return [
        {"path": path.relative_to(release_dir).as_posix(), "size": path.stat().st_size}
        for path in sorted(release_dir.rglob("*"))
        if path.is_file()
    ]


def _read_release_file_sync(release_dir: Path, relative_path: str):
    from module_runtime.paths import resolve_within_root

    path = resolve_within_root(release_dir, relative_path, must_exist=True)
    if not path.is_file():
        raise ValueError("文件不存在")
    size = path.stat().st_size
    if size > USER_MODULE_GENERATION_MAX_FILE_BYTES:
        raise ValueError("文件超过读取大小限制")
    return {
        "path": path.relative_to(release_dir).as_posix(),
        "size": size,
        "content": path.read_text(encoding="utf-8"),
    }


@router.get("/{module_id}/releases/{release_id}/files")
async def list_release_files(
    module_id: str,
    release_id: int,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """已发布 Release 的文件清单（管理员只读，供详情弹窗查看代码）。"""
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        _release, release_dir = await _resolve_release_dir(module_id, release_id)
        files = await asyncio.wait_for(
            asyncio.to_thread(_list_release_files_sync, release_dir),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        return {"success": True, "data": {"release_id": release_id, "files": files}}
    except FileNotFoundError:
        return _failure(ValueError("Release 目录不存在"), 404)
    except Exception as exc:
        return _failure(exc)


@router.get("/{module_id}/releases/{release_id}/files/content")
async def read_release_file(
    module_id: str,
    release_id: int,
    path: str = Query(min_length=1, max_length=512),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """读取已发布 Release 内的单个文件内容（512KB 上限，路径限制在 Release 目录内）。"""
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    try:
        _release, release_dir = await _resolve_release_dir(module_id, release_id)
        content = await asyncio.wait_for(
            asyncio.to_thread(_read_release_file_sync, release_dir, path),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        return {"success": True, "data": content}
    except FileNotFoundError:
        return _failure(ValueError("文件不存在"), 404)
    except Exception as exc:
        return _failure(exc)


@router.post("/{module_id}/releases/{release_id}/activate")
async def activate_release(
    module_id: str,
    release_id: int,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from model.user_modules import UserModulesModel, UserModuleStatus

    try:
        module = await asyncio.wait_for(
            asyncio.to_thread(UserModulesModel.get_module, module_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        if module and module.status == UserModuleStatus.DELETED:
            return _failure(ValueError("模块已删除，无法激活"), 400)
        await asyncio.wait_for(
            asyncio.to_thread(UserModulesModel.activate_release, module_id, release_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        try:
            await SupervisorClient().reload()
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error_code": "module_activated_supervisor_reload_failed",
                    "error": (
                        "Release 已激活，但 Supervisor 重载失败；新请求会在 Supervisor 恢复后可用: "
                        f"{exc}"
                    ),
                    "data": {"module_id": module_id, "release_id": release_id},
                },
            )
        # 激活可能改变绑定实现方的 manifest 声明（request_schema 等），即时重载注册表
        await _reload_binding_registrations()
        return {"success": True, "data": {"module_id": module_id, "release_id": release_id}}
    except Exception as exc:
        return _failure(exc)


async def _reload_binding_registrations() -> None:
    """模块版本切换/禁用后刷新本进程的动态实现方注册；失败不影响主操作结果。"""
    from services.user_module_binding_service import load_user_module_bindings

    try:
        await asyncio.wait_for(
            asyncio.to_thread(load_user_module_bindings),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("模块版本变更后重载实现方绑定注册失败，等待周期重载兜底", exc_info=True)


@router.post("/{module_id}/rollback/{release_id}")
async def rollback_release(
    module_id: str,
    release_id: int,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """回滚和激活共用同一个原子版本指针切换，保留显式语义接口。"""

    return await activate_release(module_id, release_id, authorization)


@router.post("/{module_id}/disable")
async def disable_module(
    module_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from model.user_modules import UserModulesModel

    try:
        affected = await asyncio.wait_for(
            asyncio.to_thread(UserModulesModel.disable, module_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        if affected != 1:
            return _failure(ValueError("模块不存在"), 404)
        try:
            await SupervisorClient().reload()
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error_code": "module_disabled_supervisor_reload_failed",
                    "error": (
                        "模块已禁用，但 Supervisor 重载失败；新请求会在 Supervisor 恢复后保持禁用: "
                        f"{exc}"
                    ),
                    "data": {"module_id": module_id, "enabled": False},
                },
            )
        # 禁用后绑定失效，即时刷新动态实现方注册表
        await _reload_binding_registrations()
        return {"success": True, "data": {"module_id": module_id, "enabled": False}}
    except Exception as exc:
        return _failure(exc)


@router.delete("/{module_id}")
async def delete_module(
    module_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """软删除模块：从列表隐藏并使绑定失效；Release 与历史任务记录保留。

    仅允许删除已禁用的模块（enabled=1 时返回 400，提示先禁用）。
    """
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from model.user_modules import UserModulesModel

    try:
        module = await asyncio.wait_for(
            asyncio.to_thread(UserModulesModel.get_module, module_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        if not module:
            return _failure(ValueError("模块不存在"), 404)
        if module.status == "deleted":
            return {"success": True, "data": {"module_id": module_id, "deleted": True}}
        if module.enabled or module.status == "active":
            return _failure(ValueError("模块仍在启用中，请先禁用后再删除"), 400)
        affected = await asyncio.wait_for(
            asyncio.to_thread(UserModulesModel.delete_module, module_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        if affected != 1:
            return _failure(ValueError("删除失败，请刷新后重试"), 400)
        try:
            await SupervisorClient().reload()
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error_code": "module_deleted_supervisor_reload_failed",
                    "error": (
                        "模块已删除，但 Supervisor 重载失败；Runner 会在 Supervisor 恢复后停止: "
                        f"{exc}"
                    ),
                    "data": {"module_id": module_id, "deleted": True},
                },
            )
        # 删除后绑定失效，即时刷新动态实现方注册表
        await _reload_binding_registrations()
        return {"success": True, "data": {"module_id": module_id, "deleted": True}}
    except Exception as exc:
        return _failure(exc)


class ModuleBindingCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    module_id: str = Field(min_length=3, max_length=128, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)+$")
    task_id: int = Field(gt=0)
    operation: str = Field(min_length=3, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")


@router.get("/binding-targets")
async def list_module_binding_targets(
    module_id: str = Query(min_length=3, max_length=128),
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """列出模块可绑定的能力与匹配分类下的候选任务条目。"""
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from services import user_module_binding_service as binding_service

    try:
        data = await asyncio.wait_for(
            asyncio.to_thread(binding_service.list_binding_targets, module_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        return {"success": True, "data": data}
    except Exception as exc:
        return _failure(exc)


@router.get("/{module_id}/bindings")
async def list_module_bindings(
    module_id: str,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """列出模块的全部实现方绑定（含未生效绑定的原因展示）。"""
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from services import user_module_binding_service as binding_service

    try:
        bindings = await asyncio.wait_for(
            asyncio.to_thread(binding_service.list_bindings, module_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        return {"success": True, "data": {"bindings": bindings}}
    except Exception as exc:
        return _failure(exc)


@router.post("/{module_id}/bindings")
async def create_module_binding(
    module_id: str,
    request: ModuleBindingCreateRequest,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """把模块的一个能力绑定为核心任务条目的动态实现方。"""
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from services import user_module_binding_service as binding_service

    if request.module_id != module_id:
        return JSONResponse(
            status_code=400,
            content={
                "success": False,
                "error_code": "module_id_mismatch",
                "error": "请求体 module_id 与路径不一致",
            },
        )
    try:
        binding = await asyncio.wait_for(
            asyncio.to_thread(
                binding_service.create_binding, module_id, request.task_id, request.operation
            ),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        return {"success": True, "data": binding}
    except Exception as exc:
        status_code = 404 if getattr(exc, "code", "") in {
            "MODULE_NOT_ACTIVE", "TASK_NOT_FOUND", "BINDING_NOT_FOUND"
        } else 400
        return _failure(exc, status_code)


@router.delete("/bindings/{binding_id}")
async def delete_module_binding(
    binding_id: int,
    authorization: Optional[str] = Header(default=None, alias="Authorization"),
):
    """解除实现方绑定；相关任务条目的模型下拉会在重载后移除该实现方。"""
    _admin, error = await _require_admin_user(authorization)
    if error:
        return error
    from services import user_module_binding_service as binding_service

    try:
        await asyncio.wait_for(
            asyncio.to_thread(binding_service.delete_binding, binding_id),
            timeout=USER_MODULE_DB_OPERATION_TIMEOUT_SECONDS,
        )
        return {"success": True, "data": {"binding_id": binding_id}}
    except Exception as exc:
        status_code = 404 if getattr(exc, "code", "") == "BINDING_NOT_FOUND" else 400
        return _failure(exc, status_code)
