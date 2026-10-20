"""
资源访问控制公共函数模块

从 server.py 中抽取的通用鉴权 / 权限校验函数，
供 server.py 和所有 api/*.py 路由模块共享，避免循环导入。
"""
import asyncio
from typing import Optional

from fastapi import HTTPException

from config.constant import Edition, Action

import logging

logger = logging.getLogger(__name__)


async def resolve_authenticated_user_id(auth_token: Optional[str], claimed_user_id=None) -> int:
    """
    以 Authorization token 解析真实用户身份（user_id 的唯一可信来源）。

    客户端自报的 X-User-Id 头 / URL 参数仅作一致性参考，不作鉴权依据：
    - token 缺失/无效/过期 → 401
    - 自报 user_id 与 token 属主不一致 → 401（防"伪主人"冒充）

    Args:
        auth_token: Authorization 头原值（兼容 Bearer 前缀/裸 token；
            浏览器 cookie 会话已由 auth_cookie_translation_middleware 翻译注入）
        claimed_user_id: 客户端自报的 user_id（X-User-Id 头等），可为空

    Returns:
        int: token 属主的真实 user_id

    Raises:
        HTTPException(401): token 缺失/无效，或与自报 user_id 不一致
    """
    from model.user_tokens import UserTokensModel
    from perseids_server.utils.auth_identity import normalize_authorization_token

    token = normalize_authorization_token(auth_token)
    if not token:
        raise HTTPException(status_code=401, detail="登录状态失效，请保存当前内容后重新登录")
    user_id = await asyncio.to_thread(UserTokensModel.get_user_id_by_token, token)
    if not user_id:
        raise HTTPException(status_code=401, detail="登录已过期，请保存当前内容后重新登录")
    if claimed_user_id not in (None, "") and str(claimed_user_id).strip() != str(user_id):
        raise HTTPException(status_code=401, detail="用户身份不一致，请重新登录后再试")
    return int(user_id)


def get_user_id_from_header(user_id: Optional[int]) -> int:
    """
    从 Header 参数中获取并校验 user_id
    
    Raises:
        HTTPException(400): user_id 缺失或格式错误
    """
    if user_id is None:
        raise HTTPException(status_code=400, detail="user_id is required")
    if isinstance(user_id, str) and not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id is required")
    try:
        return int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid user_id")


def check_resource_permission(resource, user_id: int, action: str) -> bool:
    """
    统一资源权限检查
    
    Args:
        resource: 资源对象（world, workflow, character等）
        user_id: 用户ID
        action: 操作类型 'view' | 'edit' | 'delete'
    
    Returns:
        bool: 是否有权限
    """
    if Edition.is_space_isolated():
        return getattr(resource, 'user_id', None) == user_id
    else:
        if action == Action.DELETE:
            return getattr(resource, 'user_id', None) == user_id
        return True


def ensure_resource_access(resource, user_id: int, action: str, resource_name: str = "资源"):
    """
    确保用户有权限访问资源，无权限则抛出异常
    
    Args:
        resource: 资源对象
        user_id: 用户ID
        action: 操作类型 'view' | 'edit' | 'delete'
        resource_name: 资源名称（用于错误提示）
    
    Returns:
        resource: 原资源对象
    
    Raises:
        HTTPException: 无权限时抛出403异常
    """
    if not check_resource_permission(resource, user_id, action):
        if action == Action.DELETE:
            raise HTTPException(status_code=403, detail=f"仅创建者可删除该{resource_name}")
        raise HTTPException(status_code=403, detail=f"无权访问该{resource_name}")
    return resource


def http_exception_message(detail, fallback: str = "请求失败") -> str:
    """把 HTTPException.detail 收成一句可展示的中文。

    FastAPI 默认错误体只有 detail，没有 message。调用方若只读 message，
    会把「仅创建者可删除该世界」显示成未知错误。
    """
    if isinstance(detail, str):
        text = detail.strip()
        return text or fallback
    if isinstance(detail, dict):
        for key in ("message", "error", "detail", "msg"):
            value = detail.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return fallback
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                msg = item.get("msg") or item.get("message")
                if isinstance(msg, str) and msg.strip():
                    parts.append(msg.strip())
        return "；".join(parts) if parts else fallback
    if detail is None:
        return fallback
    text = str(detail).strip()
    return text or fallback


def is_admin_user(user_id: int) -> bool:
    """
    判断用户是否为管理员（users.role == 'admin'）。

    注意：此函数内部导入 UsersModel 以避免顶层循环导入。
    查询异常时按非管理员处理（安全失败）。
    """
    try:
        from model.users import UsersModel
        user = UsersModel.get_by_id(user_id)
        return bool(user and getattr(user, 'role', None) == 'admin')
    except Exception as e:
        logger.warning(f"is_admin_user check failed for user {user_id}: {e}")
        return False


def ensure_world_access(world_id: int, user_id: int, action: str = Action.VIEW):
    """
    检查用户对世界的访问权限
    
    注意：此函数内部导入 WorldModel 以避免顶层循环导入。
    """
    from model.world import WorldModel
    
    world = WorldModel.get_by_id(world_id)
    if not world:
        raise HTTPException(status_code=404, detail="世界不存在")
    return ensure_resource_access(world, user_id, action, "世界")


def ensure_world_owner_or_admin(world_id: int, user_id: int):
    """
    隐藏、恢复、硬删除世界：创建者本人，或 users.role=admin 的管理员。

    查看/编辑仍走 ensure_world_access，不在这里放宽。
    世界不存在返回 404；既不是创建者也不是管理员返回 403。
    """
    from model.world import WorldModel

    world = WorldModel.get_by_id(world_id)
    if not world:
        raise HTTPException(status_code=404, detail="世界不存在")
    if getattr(world, 'user_id', None) != user_id and not is_admin_user(user_id):
        raise HTTPException(status_code=403, detail="仅创建者或管理员可删除该世界")
    return world


async def enforce_x_user_id_consistency(request):
    """
    X-User-Id 自报身份与 token 属主一致性强制校验（供中间件统一调用）。

    背景：历史上一批接口只读 X-User-Id 头认定身份、不校验 Authorization token
    属主，任何人改一个 header 即可冒充他人读写资源（"伪主人"漏洞）。本函数统一
    收口：凡携带 X-User-Id 头的 /api/ 请求，必须同时持有有效 token，且 token
    属主与该头一致。

    - 非 /api/ 请求、或未携带 X-User-Id 头 → None（放行，端点自行鉴权）
    - token 缺失/无效 → 401（missing_auth_token / invalid_auth_token）
    - token 属主 ≠ X-User-Id → 401（user_mismatch）

    认证 cookie（AUTH_COOKIE_NAME）作为 Authorization 缺失时的兜底读取，
    使本校验与 cookie 翻译中间件的执行顺序无关。

    Returns:
        None 放行；否则返回可直接回传的 JSONResponse。
    """
    from fastapi.responses import JSONResponse

    path = request.url.path
    if path != "/api" and not path.startswith("/api/"):
        return None
    claimed = (request.headers.get("x-user-id") or "").strip()
    if not claimed:
        return None

    from config.constant import AUTH_COOKIE_NAME
    from model.user_tokens import UserTokensModel
    from perseids_server.utils.auth_identity import normalize_authorization_token

    token = normalize_authorization_token(request.headers.get("authorization"))
    if not token:
        token = normalize_authorization_token(request.cookies.get(AUTH_COOKIE_NAME))
    if not token:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error_code": "missing_auth_token",
                "error": "Authorization is required",
                "detail": "登录状态失效，请保存当前内容后重新登录",
            },
        )
    try:
        user_id = await asyncio.to_thread(UserTokensModel.get_user_id_by_token, token)
    except Exception as e:
        logger.error(f"X-User-Id 一致性校验：token 解析异常: {e}")
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error_code": "auth_service_unavailable",
                "error": "auth service unavailable",
                "detail": "认证服务暂时不可用，请稍后重试",
            },
        )
    if not user_id:
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error_code": "invalid_auth_token",
                "error": "Authorization is invalid or expired",
                "detail": "登录已过期，请保存当前内容后重新登录",
            },
        )
    if str(user_id) != claimed:
        logger.warning(
            f"X-User-Id 与 token 属主不一致 - token user: {user_id}, claimed: {claimed}, path: {path}"
        )
        return JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error_code": "user_mismatch",
                "error": "user_id 与当前登录用户不一致",
                "detail": "用户身份不一致，请重新登录后再试",
            },
        )
    return None
