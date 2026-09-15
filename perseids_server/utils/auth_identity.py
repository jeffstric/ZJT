"""API 共享身份解析（底层实现）。

只负责 Authorization Token 的规范化与真实用户解析；具体接口是否允许
X-User-Id 等兼容身份，由各业务路由自行决定。

api/auth_identity.py 从此处 re-export，保持既有调用点不变。
"""
import asyncio
from typing import Optional, Tuple

from fastapi.responses import JSONResponse

from model.user_tokens import UserTokensModel


def normalize_authorization_token(value: Optional[str]) -> str:
    """返回不含 Bearer 前缀的 Token。"""
    token = str(value or "").strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    return token


async def resolve_authorization_user_id(
    value: Optional[str],
) -> Tuple[Optional[int], Optional[JSONResponse]]:
    """异步解析 Authorization，返回 ``(user_id, error_response)``。"""
    token = normalize_authorization_token(value)
    if not token:
        return None, JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error_code": "missing_auth_token",
                "error": "Authorization is required",
            },
        )

    user_id = await asyncio.to_thread(UserTokensModel.get_user_id_by_token, token)
    if not user_id:
        return None, JSONResponse(
            status_code=401,
            content={
                "success": False,
                "error_code": "invalid_auth_token",
                "error": "Authorization is invalid or expired",
            },
        )
    return int(user_id), None


def get_auth_user_id(request) -> Optional[int]:
    """读取 require_permission 装饰器注入的当前登录用户 ID。

    仅在挂了 @require_permission 的端点内可用；未鉴权端点返回 None。
    """
    return getattr(getattr(request, "state", None), "user_id", None)


def owner_mismatch_response() -> JSONResponse:
    """属主不符时统一返回 404（不泄露资源存在性，防枚举）。"""
    return JSONResponse(
        status_code=404,
        content={
            "success": False,
            "error": "资源不存在",
        },
    )


def user_mismatch_response() -> JSONResponse:
    """请求携带的 user_id 与登录身份不一致时返回 403。"""
    return JSONResponse(
        status_code=403,
        content={
            "success": False,
            "error_code": "user_mismatch",
            "error": "user_id 与当前登录用户不一致",
        },
    )


def ensure_owner(entity_user_id, auth_user_id: Optional[int]) -> Optional[JSONResponse]:
    """属主断言：资源 user_id 与当前登录用户不一致时返回 404 响应，否则 None。

    agent_tasks/chat_sessions 的 user_id 为 varchar，ai_tools/world 为 int，
    统一转 str 归一化比较。
    """
    if entity_user_id is None or auth_user_id is None:
        return owner_mismatch_response()
    if str(entity_user_id).strip() != str(auth_user_id).strip():
        return owner_mismatch_response()
    return None


def check_claimed_user_id(claimed_user_id, auth_user_id: Optional[int]) -> Optional[JSONResponse]:
    """请求体/查询参数携带的 user_id 与登录身份比对，不一致返回 403，否则 None。

    claimed_user_id 允许为空（旧客户端未携带时以登录身份为准）。
    """
    if claimed_user_id in (None, ""):
        return None
    if str(claimed_user_id).strip() != str(auth_user_id).strip():
        return user_mismatch_response()
    return None


__all__ = [
    "normalize_authorization_token",
    "resolve_authorization_user_id",
    "get_auth_user_id",
    "owner_mismatch_response",
    "user_mismatch_response",
    "ensure_owner",
    "check_claimed_user_id",
]
