"""API 共享身份解析。

只负责 Authorization Token 的规范化与真实用户解析；具体接口是否允许
X-User-Id 等兼容身份，由各业务路由自行决定。
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


__all__ = ["normalize_authorization_token", "resolve_authorization_user_id"]
