"""用户模块（接口模块）生成智能体工具集。

schema 与执行函数自 develop_f1214 起随用户模块子系统迁入主仓，注册入口经
ToolExecutor.register_enterprise_tool 注入。工具语义与 trusted-model 注入
约定见 script_writer_core/skills/generate-user-api-module/SKILL.md。
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from config.constant import (
    USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS,
    USER_MODULE_GENERATION_VALIDATION_TIMEOUT_SECONDS,
    USER_MODULE_REVIEW_OPERATION_TIMEOUT_SECONDS,
)

USER_MODULE_AGENT_TOOL_SCHEMAS = [
    {
        "name": "user_module_generation_create",
        "description": "管理员专用：创建用户 API 模块 staging generation。只建立受限草稿，不审批、不激活。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "module_id": {"type": "string", "description": "稳定命名空间模块 ID，如 vendor.service"},
                "requirement": {"type": "string", "description": "完整接口对接需求"}
            },
            "required": ["module_id", "requirement"]
        }
    },
    {
        "name": "user_module_project_search",
        "description": "管理员专用：在用户模块公开 SDK/协议范围内检索当前项目代码，不读取配置、数据库或密钥。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 50, "minimum": 1, "maximum": 200}
            },
            "required": ["query"]
        }
    },
    {
        "name": "user_module_project_read",
        "description": "管理员专用：读取公开 SDK/协议文件的指定行范围。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "default": 1, "minimum": 1},
                "end_line": {"type": "integer", "default": 400, "minimum": 1}
            },
            "required": ["path"]
        }
    },
    {
        "name": "user_module_generation_get",
        "description": "管理员专用：获取 generation 状态和文件清单。",
        "inputSchema": {
            "type": "object",
            "properties": {"generation_id": {"type": "string"}},
            "required": ["generation_id"]
        }
    },
    {
        "name": "user_module_generation_read",
        "description": "管理员专用：读取 generation staging 中的单个普通文件。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "generation_id": {"type": "string"},
                "path": {"type": "string"}
            },
            "required": ["generation_id", "path"]
        }
    },
    {
        "name": "user_module_generation_write",
        "description": "管理员专用：原子写入 generation staging 文件；路径越界和状态文件会被拒绝。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "generation_id": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"}
            },
            "required": ["generation_id", "path", "content"]
        }
    },
    {
        "name": "user_module_generation_validate",
        "description": "管理员专用：执行 Manifest、AST、导入白名单、异步方法和阻塞调用校验。不会审批发布。",
        "inputSchema": {
            "type": "object",
            "properties": {"generation_id": {"type": "string"}},
            "required": ["generation_id"]
        }
    }
]
def _run_user_module_generation(
    coroutine,
    *,
    timeout: float = USER_MODULE_GENERATION_VALIDATION_TIMEOUT_SECONDS,
):
    """Agent 当前为同步工具循环；每次独立线程内执行有 deadline 的异步服务调用。"""

    return asyncio.run(
        asyncio.wait_for(
            coroutine,
            timeout=timeout,
        )
    )


def _require_user_module_admin(user_id: str, auth_token: str) -> None:
    from model.users import UsersModel
    from model.user_tokens import UserTokensModel

    token_user_id = UserTokensModel.get_user_id_by_token(str(auth_token or ""))
    if not token_user_id or str(token_user_id) != str(user_id):
        raise PermissionError("用户模块代码生成工具认证信息无效")

    user = UsersModel.get_by_id(int(user_id))
    if not user or user.role != "admin":
        raise PermissionError("用户模块代码生成工具仅限管理员")


def _user_module_generation_service():
    from module_runtime.generation import AsyncGenerationService

    return AsyncGenerationService()


def user_module_generation_create(
    user_id: str,
    world_id: str,
    auth_token: str,
    module_id: str,
    requirement: str,
    model: Optional[str] = None,
    model_id: Optional[int] = None,
    vendor_id: Optional[int] = None,
) -> Dict[str, Any]:
    _require_user_module_admin(user_id, auth_token)
    normalized_model = str(model or "").strip()
    if not normalized_model or not model_id or int(model_id) <= 0:
        raise ValueError("当前 Agent 缺少有效的审核模型上下文")
    if not vendor_id or int(vendor_id) <= 0:
        raise ValueError("当前 Agent 缺少有效的审核模型供应商上下文")
    return _run_user_module_generation(
        _user_module_generation_service().create(
            module_id=module_id,
            requirement=requirement,
            created_by=str(user_id),
            review_model=normalized_model,
            review_model_id=int(model_id),
            review_vendor_id=int(vendor_id),
        )
    )


def user_module_project_search(
    user_id: str,
    world_id: str,
    auth_token: str,
    query: str,
    limit: int = 50,
) -> Dict[str, Any]:
    _require_user_module_admin(user_id, auth_token)
    results = _run_user_module_generation(
        _user_module_generation_service().search_project(query, limit)
    )
    return {"results": results}


def user_module_project_read(
    user_id: str,
    world_id: str,
    auth_token: str,
    path: str,
    start_line: int = 1,
    end_line: int = 400,
) -> Dict[str, Any]:
    _require_user_module_admin(user_id, auth_token)
    return _run_user_module_generation(
        _user_module_generation_service().read_project_file(path, start_line, end_line)
    )


def user_module_generation_get(
    user_id: str,
    world_id: str,
    auth_token: str,
    generation_id: str,
) -> Dict[str, Any]:
    _require_user_module_admin(user_id, auth_token)
    service = _user_module_generation_service()

    async def load():
        await service.assert_owner(generation_id, str(user_id))
        state, files = await asyncio.gather(service.get(generation_id), service.list_files(generation_id))
        return {**state, "files": files}

    return _run_user_module_generation(load())


def user_module_generation_read(
    user_id: str,
    world_id: str,
    auth_token: str,
    generation_id: str,
    path: str,
) -> Dict[str, Any]:
    _require_user_module_admin(user_id, auth_token)
    service = _user_module_generation_service()

    async def read_owned():
        await service.assert_owner(generation_id, str(user_id))
        return await service.read_file(generation_id, path)

    return _run_user_module_generation(read_owned())


def user_module_generation_write(
    user_id: str,
    world_id: str,
    auth_token: str,
    generation_id: str,
    path: str,
    content: str,
) -> Dict[str, Any]:
    _require_user_module_admin(user_id, auth_token)
    service = _user_module_generation_service()

    async def write_owned():
        await service.assert_owner(generation_id, str(user_id))
        return await service.write_file(generation_id, path, content)

    return _run_user_module_generation(write_owned())


def user_module_generation_validate(
    user_id: str,
    world_id: str,
    auth_token: str,
    generation_id: str,
) -> Dict[str, Any]:
    _require_user_module_admin(user_id, auth_token)
    service = _user_module_generation_service()

    async def validate_owned():
        await service.assert_owner(generation_id, str(user_id))
        return await service.validate(generation_id, auth_token=auth_token)

    return _run_user_module_generation(
        validate_owned(),
        timeout=(
            USER_MODULE_GENERATION_VALIDATION_TIMEOUT_SECONDS
            + USER_MODULE_REVIEW_OPERATION_TIMEOUT_SECONDS
            + USER_MODULE_GENERATION_IO_TIMEOUT_SECONDS
        ),
    )



# 工具名 → 是否需要受信模型路由注入（审核目标必须由服务端决定，防 LLM 伪造）
_USER_MODULE_TOOLS = {
    "user_module_generation_create": user_module_generation_create,
    "user_module_project_search": user_module_project_search,
    "user_module_project_read": user_module_project_read,
    "user_module_generation_get": user_module_generation_get,
    "user_module_generation_read": user_module_generation_read,
    "user_module_generation_write": user_module_generation_write,
    "user_module_generation_validate": user_module_generation_validate,
}
_USER_MODULE_TOOL_SCHEMAS = {item["name"]: item for item in USER_MODULE_AGENT_TOOL_SCHEMAS}


def register_user_module_agent_tools(register_tool) -> None:
    """把 7 个生成工具注册进主仓工具体系（register_tool 见 tool_executor）。"""
    for name, func in _USER_MODULE_TOOLS.items():
        register_tool(
            name,
            func,
            schema=_USER_MODULE_TOOL_SCHEMAS[name],
            inject_trusted_model=name == "user_module_generation_create",
        )


def unregister_user_module_agent_tools(unregister_tool) -> None:
    for name in _USER_MODULE_TOOLS:
        unregister_tool(name)
