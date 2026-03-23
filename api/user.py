"""
用户偏好 API 路由
"""
from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel
from typing import Optional, Dict, List
import logging

from model.users import UsersModel
from model.user_tokens import UserTokensModel
from config.unified_config import UnifiedConfigRegistry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user", tags=["user"])


class ImplementationPreferenceRequest(BaseModel):
    task_key: str
    implementation_name: str


@router.get("/implementation-preferences")
async def get_implementation_preferences(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取用户所有实现方偏好

    返回格式：
    {
        "code": 0,
        "data": {
            "preferences": {
                "image_edit": "gemini_duomi_v1",
                "image_to_video": "sora2_duomi_v1"
            },
            "available_implementations": {
                "image_edit": [
                    {"name": "gemini_duomi_v1", "display_name": "多米", "computing_power": 2}
                ]
            }
        }
    }
    """
    # 移除 "Bearer " 前缀
    if not auth_token:
        raise HTTPException(status_code=401, detail="需要登录")

    if auth_token.startswith("Bearer "):
        auth_token = auth_token[7:]

    # 验证 token 并获取用户ID
    user_id = UserTokensModel.get_user_id_by_token(auth_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效或已过期的认证信息")

    # 获取用户信息
    user = UsersModel.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 获取当前偏好
    current_prefs = user.implementation_preferences or {}

    # 获取所有任务类型及其可选实现方
    all_task_configs = UnifiedConfigRegistry.get_all()
    available_implementations = {}

    for task_config in all_task_configs:
        if not task_config.implementations:
            # 只使用默认实现方
            impl_config = UnifiedConfigRegistry.get_implementation(task_config.implementation)
            if impl_config:
                available_implementations[task_config.key] = [{
                    "name": task_config.implementation,
                    "display_name": impl_config.display_name,
                    "computing_power": impl_config.default_computing_power,
                    "enabled": impl_config.is_enabled()
                }]
        else:
            # 有多个可选实现方
            impls = []
            for impl_name in task_config.implementations:
                impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
                if impl_config and impl_config.is_enabled():
                    impls.append({
                        "name": impl_name,
                        "display_name": impl_config.display_name,
                        "computing_power": impl_config.default_computing_power,
                        "enabled": True
                    })
            if impls:
                available_implementations[task_config.key] = impls

    return {
        "code": 0,
        "data": {
            "preferences": current_prefs,
            "available_implementations": available_implementations
        }
    }


@router.put("/implementation-preference")
async def set_implementation_preference(
    request: ImplementationPreferenceRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    设置单个任务类型的实现方偏好
    """
    # 移除 "Bearer " 前缀
    if not auth_token:
        raise HTTPException(status_code=401, detail="需要登录")

    if auth_token.startswith("Bearer "):
        auth_token = auth_token[7:]

    # 验证 token 并获取用户ID
    user_id = UserTokensModel.get_user_id_by_token(auth_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效或已过期的认证信息")

    # 获取用户信息
    user = UsersModel.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 验证实现方是否存在
    impl_config = UnifiedConfigRegistry.get_implementation(request.implementation_name)
    if not impl_config:
        raise HTTPException(status_code=400, detail=f"实现方不存在: {request.implementation_name}")

    # 验证实现方是否已启用
    if not impl_config.is_enabled():
        raise HTTPException(status_code=400, detail=f"实现方已禁用: {request.implementation_name}")

    # 设置偏好
    success = UsersModel.set_implementation_preference(
        user_id=user_id,
        task_key=request.task_key,
        implementation_name=request.implementation_name
    )

    if success:
        return {
            "code": 0,
            "message": "偏好设置成功"
        }
    else:
        raise HTTPException(status_code=500, detail="设置失败")


@router.delete("/implementation-preference")
async def delete_implementation_preference(
    task_key: str = Query(...),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    清除单个任务类型的实现方偏好，恢复使用默认实现方
    """
    # 移除 "Bearer " 前缀
    if not auth_token:
        raise HTTPException(status_code=401, detail="需要登录")

    if auth_token.startswith("Bearer "):
        auth_token = auth_token[7:]

    # 验证 token 并获取用户ID
    user_id = UserTokensModel.get_user_id_by_token(auth_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效或已过期的认证信息")

    # 获取用户信息
    user = UsersModel.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # 清除偏好
    success = UsersModel.clear_implementation_preference(user_id, task_key)

    if success:
        return {
            "code": 0,
            "message": "偏好已清除"
        }
    else:
        raise HTTPException(status_code=500, detail="操作失败")
