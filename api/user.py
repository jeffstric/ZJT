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
from model.ai_tools import AIToolsModel
from model.implementation_stats_cache import ImplementationStatsCacheModel
from config.unified_config import UnifiedConfigRegistry, TaskCategory, get_implementation_name, get_implementation_id
from utils.config_checker import check_implementation_config_exists
from config.strategy.edition_strategy import IS_COMMUNITY_EDITION
from perseids_server.utils.token import generate_secret_key

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

    # 一次性加载所有统计数据（仅商业版）
    stats_map = {}
    if not IS_COMMUNITY_EDITION:
        stats_cache = ImplementationStatsCacheModel.get_by_days(7)
        for stat in stats_cache:
            key = f"{stat['type']}_{stat['impl_id']}"
            stats_map[key] = {
                'success_rate': float(stat['success_rate']) if stat['success_rate'] else 0,
                'avg_duration_ms': int(stat['avg_duration_ms']) if stat['avg_duration_ms'] else 0,
                'total_count': int(stat['total_count']) if stat['total_count'] else 0
            }

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

                # 获取算力配置（使用与后台一致的方法）
                power_configs = ImplementationPowerModel.get_all_powers_for_implementation(impl_name, task_config.driver_name)

                # 优先从数据库获取固定算力
                computing_power = power_configs.get(None)  # None 表示固定算力

                # 如果没有固定算力配置，尝试获取第一个时长的算力
                if computing_power is None and power_configs:
                    # 过滤掉 None 键，获取第一个时长的算力
                    duration_powers = {k: v for k, v in power_configs.items() if k is not None}
                    if duration_powers:
                        # 获取最小时长的算力
                        min_duration = min(duration_powers.keys())
                        computing_power = duration_powers[min_duration]

                # 如果数据库也没有配置，回退到代码默认值
                if computing_power is None:
                    computing_power = impl_config.default_computing_power
                    # 如果默认值是字典，取第一个值
                    if isinstance(computing_power, dict) and computing_power:
                        computing_power = list(computing_power.values())[0]

                # 获取该实现方的统计数据（仅商业版）
                impl_stats = None
                if not IS_COMMUNITY_EDITION:
                    impl_id = get_implementation_id(impl_name)
                    stat_key = f"{task_config.id}_{impl_id}"
                    impl_stats = stats_map.get(stat_key, None)

                impls.append({
                    "name": impl_name,
                    "display_name": display_name,
                    "computing_power": computing_power,
                    "enabled": True,
                    "stats": impl_stats
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

    # 社区版且没有可用实现方时，返回示例数据
    if IS_COMMUNITY_EDITION and len(available_implementations) == 0:
        available_implementations = {
            "gemini-2.5-flash-image-preview": {
                "name": "nano-banana",
                "category": "image_edit",
                "category_group": "image",
                "implementations": [
                    {"name": "gemini_duomi_v1", "display_name": "云雾", "computing_power": 95, "enabled": True, "stats": None},
                    {"name": "comfiy", "display_name": "ComfyUI", "computing_power": 92, "enabled": True, "stats": None}
                ]
            },
            "gemini-3-pro-image-preview": {
                "name": "nano-banana-Pro",
                "category": "image_edit",
                "category_group": "image",
                "implementations": [
                    {"name": "gemini_duomi_v1", "display_name": "云雾", "computing_power": 98, "enabled": True, "stats": None},
                    {"name": "comfiy", "display_name": "ComfyUI", "computing_power": 95, "enabled": True, "stats": None}
                ]
            },
            "gemini-3.1-flash-image-preview": {
                "name": "nano-banana-2",
                "category": "image_edit",
                "category_group": "image",
                "implementations": [
                    {"name": "gemini_duomi_v1", "display_name": "云雾", "computing_power": 96, "enabled": True, "stats": None},
                    {"name": "comfiy", "display_name": "ComfyUI", "computing_power": 93, "enabled": True, "stats": None}
                ]
            }
        }

    return {
        "code": 0,
        "data": {
            "preferences": current_prefs,
            "available_implementations": available_implementations,
            "is_community_edition": IS_COMMUNITY_EDITION
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


@router.get("/implementation-stats")
async def get_implementation_stats(
    days: int = Query(7, ge=1, le=90, description="统计天数范围（1-90天）"),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取实现方统计数据（成功率和平均耗时）

    商业版本功能，返回系统级各实现方的执行统计（从缓存读取）
    """
    # 社区版不支持此功能
    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")

    # 移除 "Bearer " 前缀
    if not auth_token:
        raise HTTPException(status_code=401, detail="需要登录")

    if auth_token.startswith("Bearer "):
        auth_token = auth_token[7:]

    # 验证 token（只需验证有效，不关心具体用户）
    user_id = UserTokensModel.get_user_id_by_token(auth_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效或已过期的认证信息")

    # 从缓存读取统计数据
    raw_stats = ImplementationStatsCacheModel.get_by_days(days)
    latest_update = ImplementationStatsCacheModel.get_latest_update_time(days)

    # 转换统计数据，添加 driver_key 和 implementation_name
    stats = []
    for row in raw_stats:
        task_type = row['type']
        impl_id = row['impl_id']
        impl_name = get_implementation_name(impl_id)

        # 获取对应的 driver_key
        driver_key = None
        try:
            config = UnifiedConfigRegistry.get_by_id(task_type)
            if config:
                driver_key = config.driver_name
        except Exception:
            pass

        stats.append({
            'driver_key': driver_key,
            'implementation_name': impl_name,
            'total_count': row['total_count'],
            'success_count': row['success_count'],
            'fail_count': row['fail_count'],
            'success_rate': float(row['success_rate']),
            'avg_duration_ms': row['avg_duration_ms']
        })

    return {
        "code": 0,
        "data": {
            "days": days,
            "updated_at": latest_update,
            "implementations": stats
        }
    }


@router.get("/api-token")
async def get_api_token(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取用户API Token（仅商业版可用）

    返回格式：
    {
        "code": 0,
        "data": {
            "has_token": true,
            "token": "完整的token字符串"
        }
    }
    """
    # 社区版不支持此功能
    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")

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

    # 获取API Token
    try:
        token = UsersModel.get_api_token(user_id)
        has_token = token is not None and token != ""

        logger.info(f"API token status for user {user_id}: has_token={has_token}")

        return {
            "code": 0,
            "data": {
                "has_token": has_token,
                "token": token if has_token else None
            }
        }
    except Exception as e:
        logger.error(f"Failed to get API token: {e}")
        # 如果发生错误，返回没有token的状态
        return {
            "code": 0,
            "data": {
                "has_token": False,
                "token": None
            }
        }


@router.post("/api-token")
async def create_api_token(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    生成用户API Token（仅商业版可用）

    生成后返回完整Token（仅此一次可见）

    返回格式：
    {
        "code": 0,
        "data": {
            "token": "完整token字符串"
        }
    }
    """
    # 社区版不支持此功能
    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")

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

    # 生成新Token
    new_token = generate_secret_key()

    # 保存Token
    UsersModel.set_api_token(user_id, new_token)

    return {
        "code": 0,
        "data": {
            "token": new_token
        }
    }


@router.delete("/api-token")
async def delete_api_token(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    删除用户API Token（仅商业版可用）

    返回格式：
    {
        "code": 0,
        "message": "Token已撤销"
    }
    """
    # 社区版不支持此功能
    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")

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

    # 删除Token
    UsersModel.delete_api_token(user_id)

    return {
        "code": 0,
        "message": "Token已撤销"
    }


# ==================== 智剧通Token配置接口 ====================

class ZJTTokenConfigRequest(BaseModel):
    enabled: bool


@router.get("/zjt-token-config")
async def get_zjt_token_config(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取用户智剧通Token配置（仅商业版可用）

    返回格式：
    {
        "code": 0,
        "data": {
            "enabled": true,           # 用户是否开启了智剧通Token
            "expire_days": 30,         # 管理员配置的有效期天数
            "has_personal_token": false  # 用户是否配置了自己的Token
        }
    }
    """
    # 社区版不支持此功能
    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")

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

    # 获取用户是否启用了智剧通Token
    enabled = UsersModel.get_zjt_token_enabled(user_id)

    # 获取管理员配置的有效期
    from config.config_util import get_dynamic_config_value
    expire_days = get_dynamic_config_value("zjt", "token_expire_days", default=365)

    # 获取用户是否配置了自己的Token（通过api_token字段）
    has_personal_token = UsersModel.get_api_token(user_id) is not None and UsersModel.get_api_token(user_id) != ""

    return {
        "code": 0,
        "data": {
            "enabled": enabled,
            "expire_days": expire_days,
            "has_personal_token": has_personal_token
        }
    }


@router.put("/zjt-token-config")
async def set_zjt_token_config(
    request: ZJTTokenConfigRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    设置用户智剧通Token启用状态（仅商业版可用）

    返回格式：
    {
        "code": 0,
        "message": "智剧通Token已启用"
    }
    """
    # 社区版不支持此功能
    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")

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

    # 设置启用状态
    UsersModel.set_zjt_token_enabled(user_id, request.enabled)

    message = "智剧通Token已启用" if request.enabled else "智剧通Token已禁用"

    return {
        "code": 0,
        "message": message
    }
