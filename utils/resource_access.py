"""
资源访问控制公共函数模块

从 server.py 中抽取的通用鉴权 / 权限校验函数，
供 server.py 和所有 api/*.py 路由模块共享，避免循环导入。
"""
from typing import Optional

from fastapi import HTTPException

from config.constant import Edition, Action

import logging

logger = logging.getLogger(__name__)


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
