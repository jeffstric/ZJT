"""
用户偏好 API 路由
"""
from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel
from typing import Optional, Dict, List
import logging

from model.users import UsersModel
from model.user_tokens import UserTokensModel
from model.implementation_power import ImplementationPowerModel
from config.unified_config import UnifiedConfigRegistry, TaskCategory
from utils.config_checker import check_implementation_config_exists

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

    # 获取当前激活组的偏好
    current_prefs = UsersModel.get_all_preferences(user_id)

    # 获取所有任务类型及其可选实现方
    all_task_configs = UnifiedConfigRegistry.get_all()
    available_implementations = {}

    # 定义分类分组
    category_groups = {
        'image': [TaskCategory.IMAGE_EDIT, TaskCategory.TEXT_TO_IMAGE, TaskCategory.VISUAL_ENHANCE],
        'video': [TaskCategory.IMAGE_TO_VIDEO, TaskCategory.TEXT_TO_VIDEO],
    }

    for task_config in all_task_configs:
        # 只处理有多个可选实现方的任务
        if not task_config.implementations or len(task_config.implementations) <= 1:
            continue

        # 过滤出已配置且启用的实现方
        impls = []
        for impl_name in task_config.implementations:
            # 检查实现方是否已配置
            if not check_implementation_config_exists(impl_name):
                continue

            impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
            if impl_config and impl_config.is_enabled():
                # 使用与后台一致的方式获取 display_name
                # 参考 admin.py Line 1114
                display_name = impl_config.display_name

                # 对于 API 聚合器站点，从 system_config 读取站点名称
                if impl_config.site_number is not None:
                    try:
                        from config.config_util import get_dynamic_config_value
                        site_id = f"site_{impl_config.site_number}"
                        site_name = get_dynamic_config_value("api_aggregator", site_id, "name", default=site_id)
                        display_name = site_name
                    except Exception:
                        pass

                # 对于非聚合站点，优先使用数据库配置的 display_name
                else:
                    db_config = ImplementationPowerModel.get_config(impl_name, task_config.driver_name)
                    if db_config and db_config.get('display_name'):
                        display_name = db_config['display_name']

                impls.append({
                    "name": impl_name,
                    "display_name": display_name,
                    "computing_power": impl_config.default_computing_power,
                    "enabled": True
                })

        # 只保留有多个可选实现方的任务
        if len(impls) > 1:
            # 确定任务所属的分类组
            category_group = None
            for group_name, categories in category_groups.items():
                if task_config.category in categories or any(cat in categories for cat in task_config.categories):
                    category_group = group_name
                    break

            available_implementations[task_config.key] = {
                "name": task_config.name,
                "category": task_config.category,
                "category_group": category_group,
                "implementations": impls
            }

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
        implementation=request.implementation_name
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
