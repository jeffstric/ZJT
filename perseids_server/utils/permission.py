"""
权限验证装饰器模块
提供权限检查功能，用于API接口的权限控制

当前实现：Authorization Bearer token 真实校验（无效/缺失 → 401），
通过后把解析出的 user_id 注入 request.state.user_id 供业务层做属主断言。
权限点（permission code）暂映射为"登录即可"，字符串保留供未来接入
完整权限表体系；管理类端点请使用 api/admin.py 的 require_admin。
"""

from functools import wraps
from typing import List, Union
from fastapi import Request, HTTPException
import asyncio
import logging

from model.users import UsersModel

from perseids_server.utils.auth_identity import (
    resolve_authorization_user_id,
)

logger = logging.getLogger(__name__)


def require_permission(permission: Union[str, List[str]], check_mode: str = "any"):
    """
    权限验证装饰器

    Args:
        permission: 需要的权限代码，可以是单个权限字符串或权限列表
                   格式如: "video_workflow:view" 或 ["video_workflow:view", "video_workflow:create"]
                   当前版本仅要求登录（token 有效），权限点保留供未来扩展
        check_mode: 权限检查模式
                   - "any": 只要有任意一个权限即可（默认）
                   - "all": 需要拥有所有权限

    Usage:
        @app.post("/api/video-workflow")
        @require_permission("video_workflow:create")
        async def create_workflow(request: Request):
            user_id = request.state.user_id  # 已验证的登录用户
    """
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取 Request 对象
            request = None
            for arg in args:
                if isinstance(arg, Request):
                    request = arg
                    break

            if not request:
                # 从 kwargs 中查找
                request = kwargs.get('request')

            if not request:
                logger.error("无法获取 Request 对象，权限验证失败")
                raise HTTPException(status_code=500, detail="内部错误：无法获取请求对象")

            # 真实鉴权：解析 Authorization Bearer token（缺失/无效 → 401）。
            # header 缺失时回退 ?auth_token= 查询参数，兼容存量前端调用
            #（token 均为 user_tokens 表真实凭证，校验强度一致）。
            from perseids_server.utils.auth_identity import normalize_authorization_token
            auth_value = request.headers.get('authorization')
            if not normalize_authorization_token(auth_value):
                query_token = (request.query_params.get('auth_token') or '').strip()
                if query_token:
                    auth_value = query_token
            user_id, error_response = await resolve_authorization_user_id(auth_value)
            if error_response is not None:
                return error_response

            # 注入已验证身份，供业务层做属主断言（get_auth_user_id(request)）
            request.state.user_id = user_id

            # 调用原函数
            return await func(*args, **kwargs)

        return wrapper
    return decorator


def has_permission(user_id: int, permission: str) -> bool:
    """
    检查用户是否拥有指定权限

    Args:
        user_id: 用户ID
        permission: 权限代码，如 "video_workflow:view"

    Returns:
        bool: 是否拥有权限
    """
    # TODO: 接入完整权限表体系后，按用户权限组判定
    # 当前权限点全部映射为"登录即可"，HTTP 层鉴权由 require_permission 完成
    logger.debug(f"检查用户 {user_id} 是否拥有权限 {permission}（登录即持有）")
    return True


def get_user_permissions(user_id: int) -> List[str]:
    """
    获取用户的所有权限列表

    Args:
        user_id: 用户ID

    Returns:
        List[str]: 权限代码列表
    """
    # TODO: 接入完整权限表体系后，从权限组查询并缓存
    logger.debug(f"获取用户 {user_id} 的权限列表（空权限表，返回空列表）")
    return []


def clear_user_permission_cache(user_id: int):
    """
    清除用户的权限缓存
    当用户权限发生变更时调用

    Args:
        user_id: 用户ID
    """
    # TODO: 接入完整权限表体系后，删除 Redis 中的用户权限缓存
    logger.debug(f"清除用户 {user_id} 的权限缓存（空实现）")
    pass


def admin_required(func):
    """
    管理员权限装饰器
    要求用户拥有管理员权限（role == 'admin'）

    Usage:
        @app.get("/api/admin/users")
        @admin_required
        async def list_users(request: Request):
            pass
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # 获取 Request 对象
        request = None
        for arg in args:
            if isinstance(arg, Request):
                request = arg
                break

        if not request:
            request = kwargs.get('request')

        if not request:
            logger.error("无法获取 Request 对象，管理员权限验证失败")
            raise HTTPException(status_code=500, detail="内部错误：无法获取请求对象")

        # 先做登录鉴权，再校验管理员角色
        user_id, error_response = await resolve_authorization_user_id(
            request.headers.get('authorization')
        )
        if error_response is not None:
            return error_response

        user = await asyncio.to_thread(UsersModel.get_by_id, user_id)
        if not user or getattr(user, 'role', None) != 'admin':
            raise HTTPException(status_code=403, detail="需要管理员权限")

        request.state.user_id = user_id

        return await func(*args, **kwargs)

    return wrapper
