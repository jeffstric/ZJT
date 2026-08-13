"""
管理员 API 路由
"""
from fastapi import APIRouter, HTTPException, Header, Query, Path
from pydantic import BaseModel
from typing import Optional, List, Union
import logging
import httpx
import asyncio
from datetime import datetime

from model.users import UsersModel, User
from model.user_tokens import UserTokensModel
from model.computing_power import ComputingPowerModel
from model.computing_power_log import ComputingPowerLogModel
from model.video_workflow import VideoWorkflowModel
from model.ai_tools import AIToolsModel
from model.ai_tools_log import AIToolsLogModel
from model.implementation_attempts import ImplementationAttemptModel
from config.unified_config import UnifiedConfigRegistry, IMPLEMENTATION_FROM_ID, TaskCategory
from model.system_config import SystemConfigModel
from model.system_config_history import SystemConfigHistoryModel
from config.config_util import get_current_env, invalidate_dynamic_cache
from config.default_configs import init_default_configs, get_default_config_by_key
from utils.log_sanitizer import mask_phone
from config.constant import GEMINI_URL_FORMATS, DRIVER_IMPLEMENTATION_MAPPING
from config.strategy import EditionStrategy, IS_COMMUNITY_EDITION

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _is_runninghub_key_pool_config(config_key: str) -> bool:
    return bool(config_key) and (
        config_key.startswith('runninghub.key.')
        or config_key.startswith('runninghub.key_pool.')
    )


def _require_runninghub_key_pool_config_access(config_keys) -> None:
    """阻止社区版从通用配置 API 旁路读写商业密钥池配置。"""
    if not any(_is_runninghub_key_pool_config(key) for key in config_keys):
        return
    from task.runninghub_key_pool import is_available
    if not is_available():
        raise HTTPException(status_code=403, detail='此功能仅商业版本可用')


def _get_enterprise_admin_status() -> dict[str, object]:
    """读取 Enterprise 实际加载状态，避免仅按目录/config 误判。"""
    from utils.enterprise_loader import enterprise_loader

    return enterprise_loader.get_runtime_status()


async def require_admin(auth_token: str = Header(None, alias="Authorization")) -> User:
    """
    管理员权限校验中间件
    从 Authorization header 中获取 token，验证用户是否为管理员
    """
    if not auth_token:
        raise HTTPException(status_code=401, detail="需要登录")
    
    # 移除 "Bearer " 前缀
    if auth_token.startswith("Bearer "):
        auth_token = auth_token[7:]
    
    # 验证 token 并获取用户ID
    user_id = UserTokensModel.get_user_id_by_token(auth_token)
    if not user_id:
        raise HTTPException(status_code=401, detail="无效或已过期的认证信息")
    
    # 获取用户信息
    user = UsersModel.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    
    # 检查管理员权限
    if user.role != 'admin':
        raise HTTPException(status_code=403, detail="需要管理员权限")
    
    return user


@router.get("/dashboard")
async def admin_dashboard(auth_token: str = Header(None, alias="Authorization")):
    """
    管理员仪表盘数据
    返回用户总数、最近3天活跃工作流数量
    """
    admin = await require_admin(auth_token)
    
    try:
        total_users = UsersModel.get_total_count()
        active_workflows_3d = VideoWorkflowModel.count_active_recent_days(days=3)
        
        from task.runninghub_key_pool import is_available as is_runninghub_key_pool_available
        from services.branding import is_available as is_branding_available
        enterprise_status = _get_enterprise_admin_status()
        return {
            "code": 0,
            "data": {
                "total_users": total_users,
                "active_workflows_3d": active_workflows_3d,
                # UI 的运行模式必须以 Enterprise 是否完整注册为准；静态目录存在
                # 不能代表 PyArmor 和注册流程可用。
                "is_community_edition": not bool(
                    enterprise_status["registration_ready"]
                ),
                "enterprise": enterprise_status,
                "features": {
                    "runninghub_key_pool": is_runninghub_key_pool_available(),
                    "commercial_license_admin": bool(
                        enterprise_status["license_control_available"]
                    ),
                    # 品牌定制：仅企业版可用。工作室版同样注入了 branding provider，
                    # 但 is_available() 在 studio license 下经严格判断返回 False，
                    # 前端据此隐藏品牌定制入口。
                    "branding": is_branding_available(),
                },
            }
        }
    except Exception as e:
        logger.error(f"Failed to get admin dashboard data: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/monthly-active-users")
async def admin_monthly_active_users(
    year: int = Query(None),
    month: int = Query(None, ge=1, le=12),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    统计月活跃用户数（间隔超过3天且消耗算力的用户）
    活跃用户定义：在指定月份内有至少2条算力消耗记录，且最早和最晚记录间隔>=3天
    """
    admin = await require_admin(auth_token)

    # 默认使用当前年月
    if year is None or month is None:
        from datetime import datetime
        now = datetime.now()
        year = year or now.year
        month = month or now.month

    try:
        count = ComputingPowerLogModel.count_monthly_active_users(year, month)
        return {
            "code": 0,
            "data": {
                "year": year,
                "month": month,
                "active_user_count": count
            }
        }
    except Exception as e:
        logger.error(f"Failed to get monthly active users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/dashboard/model-analysis")
async def admin_model_analysis(
    days: int = Query(1, ge=1, le=30),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    模型分析 - 各模型及其供应商的成功/失败统计
    按模型类型分组聚合，支持展开查看各供应商详情
    """
    await require_admin(auth_token)

    try:
        parsed_start = datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
        parsed_end = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
        if parsed_start and parsed_end and parsed_start > parsed_end:
            raise HTTPException(status_code=400, detail="start_date must be earlier than or equal to end_date")

        raw_stats, raw_daily_stats = await asyncio.gather(
            asyncio.to_thread(
                ImplementationAttemptModel.get_stats,
                days=days,
                start_date=start_date,
                end_date=end_date
            ),
            asyncio.to_thread(
                ImplementationAttemptModel.get_daily_stats,
                days=days,
                start_date=start_date,
                end_date=end_date
            )
        )

        # 获取类型ID -> 名称映射
        type_name_map = UnifiedConfigRegistry.get_name_map()

        # 预置所有启用的视频类任务类型，避免新增模型后因暂无数据而在仪表盘消失
        video_categories = {
            TaskCategory.IMAGE_TO_VIDEO,
            TaskCategory.TEXT_TO_VIDEO,
            TaskCategory.DIGITAL_HUMAN,
        }
        all_video_type_ids = {
            c.id for c in UnifiedConfigRegistry.get_all_enabled()
            if c.category in video_categories or any(cat in video_categories for cat in c.categories)
        }

        # 按 type 分组（无数据的类型保留空列表，total=0）
        type_groups = {t: [] for t in all_video_type_ids}
        for row in raw_stats:
            t = row['type']
            if t not in type_groups:
                type_groups[t] = []
            type_groups[t].append(row)

        # 构建模型列表
        models = []
        for task_type, providers_raw in sorted(type_groups.items(), key=lambda x: -sum(r['total_count'] for r in x[1])):
            total = sum(r['total_count'] for r in providers_raw)
            success = sum(r['success_count'] for r in providers_raw)
            fail = sum(r['fail_count'] for r in providers_raw)
            success_rate = (success / total * 100) if total > 0 else 0.0

            # 构建供应商列表
            providers = []
            for r in sorted(providers_raw, key=lambda x: -x['total_count']):
                impl_id = r['implementation']
                impl_name = IMPLEMENTATION_FROM_ID.get(impl_id, f'unknown_{impl_id}')
                display_name = impl_name
                impl_config = UnifiedConfigRegistry.get_implementation(impl_name)
                if impl_config and impl_config.display_name:
                    display_name = impl_config.display_name

                providers.append({
                    'implementation': impl_id,
                    'name': impl_name,
                    'display_name': display_name,
                    'total': r['total_count'],
                    'success': r['success_count'],
                    'fail': r['fail_count'],
                    'success_rate': r['success_rate'],
                    'avg_duration_ms': r['avg_duration_ms']
                })

            models.append({
                'type': task_type,
                'name': type_name_map.get(task_type, f'未知类型({task_type})'),
                'total': total,
                'success': success,
                'fail': fail,
                'success_rate': round(success_rate, 2),
                'providers': providers
            })

        daily_groups = {}
        for row in raw_daily_stats:
            stat_date = row['date']
            if stat_date not in daily_groups:
                daily_groups[stat_date] = {
                    'date': stat_date,
                    'total': 0,
                    'success': 0,
                    'fail': 0,
                    'models': {}
                }

            day_group = daily_groups[stat_date]
            day_group['total'] += row['total_count']
            day_group['success'] += row['success_count']
            day_group['fail'] += row['fail_count']

            task_type = row['type']
            if task_type not in day_group['models']:
                day_group['models'][task_type] = {
                    'type': task_type,
                    'name': type_name_map.get(task_type, f'未知类型({task_type})'),
                    'total': 0,
                    'success': 0,
                    'fail': 0
                }
            model_group = day_group['models'][task_type]
            model_group['total'] += row['total_count']
            model_group['success'] += row['success_count']
            model_group['fail'] += row['fail_count']

        daily = []
        for day_group in sorted(daily_groups.values(), key=lambda x: x['date']):
            day_total = day_group['total']
            day_group['success_rate'] = round((day_group['success'] / day_total * 100) if day_total > 0 else 0.0, 2)
            day_group['models'] = [
                {
                    **model_group,
                    'success_rate': round((model_group['success'] / model_group['total'] * 100) if model_group['total'] > 0 else 0.0, 2)
                }
                for model_group in sorted(day_group['models'].values(), key=lambda x: -x['total'])
            ]
            daily.append(day_group)

        return {
            "code": 0,
            "data": {
                "days": days,
                "start_date": start_date,
                "end_date": end_date,
                "models": models,
                "daily": daily
            }
        }
    except HTTPException:
        raise
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format, expected YYYY-MM-DD")
    except Exception as e:
        logger.error(f"Failed to get model analysis: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ai-tools/timeline")
async def admin_ai_tools_timeline(
    ai_tool_id: Optional[int] = Query(None, description="ai_tools.id"),
    project_id: Optional[str] = Query(None, description="上游任务ID（Duomi 等）"),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员查看某任务的事件时间线（用于排查任务耗时/卡点/轮询节奏）
    支持按 ai_tool_id 或 project_id 查询，不限用户。
    """
    await require_admin(auth_token)

    if not ai_tool_id and not project_id:
        raise HTTPException(status_code=400, detail="需要提供 ai_tool_id 或 project_id")

    try:
        if project_id:
            logs = await asyncio.to_thread(AIToolsLogModel.list_by_project_id, project_id)
        else:
            logs = await asyncio.to_thread(AIToolsLogModel.list_by_ai_tool, ai_tool_id)

        # 尽量补全 ai_tool_id / project_id 便于前端展示
        resolved_ai_tool_id = ai_tool_id
        resolved_project_id = project_id
        record_status = None
        if logs:
            resolved_ai_tool_id = resolved_ai_tool_id or logs[0].ai_tool_id
            resolved_project_id = resolved_project_id or logs[0].project_id
        if resolved_ai_tool_id:
            rec = AIToolsModel.get_by_id(resolved_ai_tool_id)
            if rec:
                record_status = rec.status
                resolved_project_id = resolved_project_id or rec.project_id

        return {
            'success': True,
            'data': {
                'ai_tool_id': resolved_ai_tool_id,
                'project_id': resolved_project_id,
                'status': record_status,
                'timeline': [log.to_dict() for log in logs]
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get ai_tools timeline: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users")
async def admin_list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = Query(None),
    status: Optional[int] = Query(None),
    role: Optional[str] = Query(None),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员获取用户列表
    """
    admin = await require_admin(auth_token)
    
    try:
        result = UsersModel.list_all(
            page=page,
            page_size=page_size,
            keyword=keyword,
            status=status,
            role=role
        )
        
        # 为每个用户添加算力信息
        for user in result['data']:
            power = ComputingPowerModel.get_by_user_id(user['user_id'])
            user['computing_power'] = power.computing_power if power else 0
        
        return {
            "code": 0,
            "data": result
        }
    except Exception as e:
        logger.error(f"Failed to list users: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}")
async def admin_get_user(
    user_id: int = Path(...),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员获取用户详情
    """
    admin = await require_admin(auth_token)
    
    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        user_dict = user.to_dict()
        
        # 添加算力信息
        power = ComputingPowerModel.get_by_user_id(user_id)
        user_dict['computing_power'] = power.computing_power if power else 0
        
        return {
            "code": 0,
            "data": user_dict
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user {user_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateUserStatusRequest(BaseModel):
    status: int


@router.put("/users/{user_id}/status")
async def admin_update_user_status(
    user_id: int = Path(...),
    request: UpdateUserStatusRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员更新用户状态（0-禁用, 1-正常）
    禁用用户时会自动删除其所有 token，强制登出
    """
    admin = await require_admin(auth_token)
    
    # 禁止管理员禁用自己
    if user_id == admin.id and request.status == 0:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    
    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        # 更新用户状态
        UsersModel.update_status(user_id, request.status)
        
        # 如果是禁用操作，删除该用户的所有 token（强制登出）
        if request.status == 0:
            try:
                UserTokensModel.delete_by_user_id(user_id)
                logger.info(f"Deleted all tokens for disabled user {user_id}")
            except Exception as e:
                logger.error(f"Failed to delete tokens for user {user_id}: {e}")
                # 不影响主流程，继续执行
        
        return {
            "code": 0,
            "message": "状态更新成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user {user_id} status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateUserRoleRequest(BaseModel):
    role: str


@router.put("/users/{user_id}/role")
async def admin_update_user_role(
    user_id: int = Path(...),
    request: UpdateUserRoleRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员更新用户角色（user/admin）
    """
    admin = await require_admin(auth_token)
    
    # 禁止管理员降级自己
    if user_id == admin.id and request.role != 'admin':
        raise HTTPException(status_code=400, detail="不能降级自己的权限")
    
    if request.role not in ('user', 'admin'):
        raise HTTPException(status_code=400, detail="无效的角色")
    
    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        UsersModel.update_role(user_id, request.role)
        
        return {
            "code": 0,
            "message": "角色更新成功"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update user {user_id} role: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class AdjustPowerRequest(BaseModel):
    amount: int
    reason: str


@router.post("/users/{user_id}/power")
async def admin_adjust_user_power(
    user_id: int = Path(...),
    request: AdjustPowerRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员调整用户算力
    amount: 正数增加，负数扣减
    """
    admin = await require_admin(auth_token)
    
    if not request.reason or not request.reason.strip():
        raise HTTPException(status_code=400, detail="请填写调整原因")
    
    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")
        
        old_power, new_power = ComputingPowerModel.admin_adjust(
            user_id=user_id,
            amount=request.amount,
            reason=f"管理员({admin.phone})调整: {request.reason}"
        )
        
        return {
            "code": 0,
            "message": "算力调整成功",
            "data": {
                "old_power": old_power,
                "new_power": new_power
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to adjust user {user_id} power: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SetZJTTokenRequest(BaseModel):
    enabled: bool


class SetZJTTokenExpireRequest(BaseModel):
    expire_at: Optional[str]  # 过期时间 ISO格式字符串，null表示永不过期


@router.put("/users/{user_id}/zjt-token")
async def admin_set_user_zjt_token(
    user_id: int = Path(...),
    request: SetZJTTokenRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员设置用户智剧通Token启用状态（仅商业版）
    """
    from config.strategy.edition_strategy import IS_COMMUNITY_EDITION
    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")

    admin = await require_admin(auth_token)

    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        UsersModel.set_zjt_token_enabled(user_id, request.enabled)

        message = "已启用智剧通Token" if request.enabled else "已禁用智剧通Token"
        logger.info(
            "Admin %s set user %s zjt_token_enabled to %s",
            mask_phone(admin.phone),
            user_id,
            request.enabled,
        )

        return {
            "code": 0,
            "message": message
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set user {user_id} zjt_token_enabled: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/{user_id}/zjt-token")
async def admin_get_user_zjt_token(
    user_id: int = Path(...),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取用户智剧通Token配置（仅商业版）
    """
    from config.strategy.edition_strategy import IS_COMMUNITY_EDITION
    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")

    await require_admin(auth_token)

    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        return {
            "code": 0,
            "data": {
                "zjt_token_enabled": UsersModel.get_zjt_token_enabled(user_id),
                "zjt_token_expire_at": UsersModel.get_zjt_token_expire_at(user_id)
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get user {user_id} zjt token config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/users/{user_id}/zjt-token-expire")
async def admin_set_user_zjt_token_expire(
    user_id: int = Path(...),
    request: SetZJTTokenExpireRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    管理员设置用户智剧通Token过期时间（仅商业版）
    expire_at: 过期时间 ISO格式字符串，null表示永不过期
    """
    from config.strategy.edition_strategy import IS_COMMUNITY_EDITION
    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")

    admin = await require_admin(auth_token)

    try:
        user = UsersModel.get_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="用户不存在")

        expire_at = None
        message = "智剧通Token已设置为永不过期"

        if request.expire_at:
            # 解析日期字符串
            from datetime import datetime
            try:
                expire_at = datetime.strptime(request.expire_at, "%Y-%m-%d")
                # 设置为当天 23:59:59
                expire_at = expire_at.replace(hour=23, minute=59, second=59)
                message = f"智剧通Token过期时间已调整为 {request.expire_at}"
            except ValueError:
                raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD 格式")

        UsersModel.set_zjt_token_expire_at(user_id, expire_at)
        logger.info(
            "Admin %s set user %s zjt_token_expire_at to %s",
            mask_phone(admin.phone),
            user_id,
            expire_at,
        )

        return {
            "code": 0,
            "message": message
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to set user {user_id} zjt_token_expire_at: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 系统配置管理 API ====================


@router.get("/config")
async def admin_list_configs(
    keyword: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取系统配置列表
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    try:
        result = SystemConfigModel.search(
            env=env,
            keyword=keyword,
            page=page,
            page_size=page_size
        )

        from task.runninghub_key_pool import is_available as is_key_pool_available
        if not is_key_pool_available():
            result['data'] = [
                config for config in result['data']
                if not _is_runninghub_key_pool_config(config.get('config_key', ''))
            ]
        
        # 敏感配置在列表中脱敏显示
        for config in result['data']:
            if config['is_sensitive']:
                config['config_value'] = SystemConfigModel.mask_sensitive_value(
                    str(config['config_value']) if config['config_value'] else ''
                )
        
        return {
            "code": 0,
            "data": result
        }
    except Exception as e:
        logger.error(f"Failed to list configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/raw")
async def admin_get_config_raw_value(
    key: str = Query(..., description="配置键"),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取配置的完整值（不脱敏），用于查看敏感配置
    """
    admin = await require_admin(auth_token)
    _require_runninghub_key_pool_config_access([key])
    env = get_current_env()
    
    try:
        config = SystemConfigModel.get_by_key(env, key)
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        return {
            "code": 0,
            "data": {
                "config_key": config.config_key,
                "config_value": config.config_value
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get raw config {key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config/quick-configs")
async def admin_get_quick_configs(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取快速配置项列表
    返回需要在快速配置弹窗中显示的配置项
    """
    await require_admin(auth_token)
    
    from config.default_configs import get_quick_configs
    configs = get_quick_configs()
    
    return {
        "code": 0,
        "message": "获取成功",
        "data": {
            "configs": configs
        }
    }


@router.get("/config/{config_key:path}")
async def admin_get_config(
    config_key: str = Path(...),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取单个配置详情（包含修改历史）
    """
    admin = await require_admin(auth_token)
    _require_runninghub_key_pool_config_access([config_key])
    env = get_current_env()
    
    try:
        config = SystemConfigModel.get_by_key(env, config_key)
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        config_dict = config.to_dict()
        
        # 敏感配置脱敏显示
        if config.is_sensitive:
            config_dict['config_value'] = config.get_display_value()
        
        # 获取修改历史
        histories = SystemConfigHistoryModel.get_by_key(env, config_key, limit=10)
        config_dict['history'] = [h.to_dict() for h in histories]
        
        return {
            "code": 0,
            "data": config_dict
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get config {config_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class BatchConfigItem(BaseModel):
    key: str
    value: str


class BatchConfigRequest(BaseModel):
    configs: List[BatchConfigItem]


@router.put("/config/batch")
async def admin_batch_update_configs(
    request: BatchConfigRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    批量更新配置值
    用于快速配置功能，一次性更新多个配置项
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    if not request.configs:
        raise HTTPException(status_code=400, detail="配置列表不能为空")

    config_keys = [item.key for item in request.configs]
    _require_runninghub_key_pool_config_access(config_keys)
    is_allowed, error_msg = EditionStrategy.check_aggregator_sites(config_keys)
    if not is_allowed:
        raise HTTPException(status_code=403, detail=error_msg)

    results = []
    errors = []
    
    for item in request.configs:
        try:
            # 禁止通过管理后台修改 test_mode 配置（仅允许脚本修改，防止生产环境误开启挡板）
            if item.key.startswith('test_mode'):
                errors.append(f"{item.key}: test_mode 配置仅允许通过脚本修改，禁止在管理后台修改")
                continue

            config = SystemConfigModel.get_by_key(env, item.key)

            # 如果配置不存在，尝试从默认配置中获取定义并创建
            if not config:
                config_def = get_default_config_by_key(item.key)
                if not config_def:
                    errors.append(f"{item.key}: 配置不存在且无默认定义")
                    continue

                # 创建新配置
                config_id = SystemConfigModel.create(
                    env=env,
                    config_key=item.key,
                    config_value=item.value,
                    value_type=config_def['value_type'],
                    description=config_def['description'],
                    editable=1 if config_def['editable'] else 0,
                    is_sensitive=1 if config_def['is_sensitive'] else 0,
                    updated_by=admin.id
                )
                results.append({
                    "key": item.key,
                    "status": "created"
                })
                logger.info(f"Auto-created config {item.key} with id {config_id}")
                continue

            if not config.editable:
                errors.append(f"{item.key}: 该配置不允许修改")
                continue

            old_value = config.config_value
            new_value = item.value

            # 跳过未修改的配置
            if old_value == new_value:
                results.append({
                    "key": item.key,
                    "status": "unchanged"
                })
                continue

            # 更新配置
            SystemConfigModel.update_value(config.id, new_value, admin.id)

            results.append({
                "key": item.key,
                "status": "updated"
            })
        except Exception as e:
            logger.error(f"Failed to update config {item.key}: {e}")
            errors.append(f"{item.key}: {str(e)}")
    
    updated_count = len([r for r in results if r['status'] == 'updated'])
    created_count = len([r for r in results if r['status'] == 'created'])

    return {
        "code": 0,
        "message": f"批量更新完成，新建 {created_count} 条，更新 {updated_count} 条配置",
        "data": {
            "results": results,
            "errors": errors
        }
    }


class UpdateConfigRequest(BaseModel):
    value: Union[str, int, float, bool]
    value_type: Optional[str] = None


@router.put("/config/{config_key:path}")
async def admin_update_config(
    config_key: str = Path(...),
    request: UpdateConfigRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    更新配置值
    """
    admin = await require_admin(auth_token)
    _require_runninghub_key_pool_config_access([config_key])
    env = get_current_env()
    
    try:
        config = SystemConfigModel.get_by_key(env, config_key)
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        # 检查是否可编辑
        if not config.editable:
            raise HTTPException(status_code=403, detail="该配置不允许修改")

        # 禁止通过管理后台修改 test_mode 配置（仅允许脚本修改，防止生产环境误开启挡板）
        if config_key.startswith('test_mode'):
            raise HTTPException(status_code=403, detail="test_mode 配置仅允许通过脚本修改，禁止在管理后台修改")

        old_value = config.config_value
        # 将值转换为字符串存储
        new_value = str(request.value) if request.value is not None else ''
        value_type = request.value_type or config.value_type
        
        # 更新配置
        SystemConfigModel.update_value(config.id, new_value, admin.id)
        
        # 记录修改历史
        if old_value != new_value:
            SystemConfigHistoryModel.create(
                config_id=config.id,
                env=env,
                config_key=config_key,
                old_value=old_value,
                new_value=new_value,
                value_type=value_type,
                is_sensitive=config.is_sensitive,
                updated_by=admin.id
            )
        
        # 清除缓存
        invalidate_dynamic_cache(config_key)
        
        return {
            "code": 0,
            "message": "配置更新成功",
            "data": {
                "old_value": SystemConfigModel.mask_sensitive_value(old_value) if config.is_sensitive else old_value,
                "new_value": SystemConfigModel.mask_sensitive_value(new_value) if config.is_sensitive else new_value
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update config {config_key}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/reload")
async def admin_reload_configs(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    重新加载所有配置（清除缓存）
    """
    admin = await require_admin(auth_token)
    
    try:
        invalidate_dynamic_cache()
        
        return {
            "code": 0,
            "message": "配置缓存已清除"
        }
    except Exception as e:
        logger.error(f"Failed to reload configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/config/init")
async def admin_init_configs(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    初始化默认配置（从 YAML 导入到数据库）
    仅插入数据库中不存在的配置
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    try:
        inserted_count = init_default_configs(env, admin.id)
        
        return {
            "code": 0,
            "message": f"初始化完成，新增 {inserted_count} 条配置",
            "data": {
                "inserted_count": inserted_count,
                "env": env
            }
        }
    except Exception as e:
        logger.error(f"Failed to init configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/config-history")
async def admin_list_config_history(
    config_key: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取配置修改历史列表
    """
    admin = await require_admin(auth_token)
    env = get_current_env()
    
    try:
        result = SystemConfigHistoryModel.search(
            env=env,
            config_key=config_key,
            page=page,
            page_size=page_size
        )
        
        return {
            "code": 0,
            "data": result
        }
    except Exception as e:
        logger.error(f"Failed to list config history: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class TestGoogleRequest(BaseModel):
    api_key: str
    base_url: Optional[str] = None


class TestQwenRequest(BaseModel):
    api_key: str
    base_url: Optional[str] = None


@router.post("/config/test-google")
async def admin_test_google_connection(
    request: TestGoogleRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    测试 Google/Gemini API 连接
    通过发送一个简单的请求验证 API Key 有效性
    支持两种 URL 格式自动尝试（第三方代理格式和 Google 官方格式）
    """
    admin = await require_admin(auth_token)
    
    if not request.api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")
    
    # 构建请求 URL
    base_url = request.base_url or "https://api.jiekou.ai"
    base_url = base_url.rstrip("/")
    
    # 移除 /openai 后缀（如果有）
    if base_url.endswith('/openai'):
        base_url = base_url[:-7]
    
    # 测试模型
    test_model = "gemini-3-flash-preview"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {request.api_key}"
    }
    
    # 构建最简单的测试请求
    test_payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": "Hi"}]
            }
        ],
        "generationConfig": {
            "maxOutputTokens": 10,
            "temperature": 0.1
        }
    }
    
    # 记录最后一次错误信息
    last_error = None
    last_error_message = None
    
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            # 依次尝试两种 URL 格式
            for fmt_name, fmt_path in GEMINI_URL_FORMATS.items():
                url = f"{base_url}{fmt_path.format(model=test_model)}"
                
                try:
                    response = await client.post(url, headers=headers, json=test_payload)
                    
                    if response.status_code == 200:
                        # 验证响应体有效性
                        try:
                            resp_json = response.json()
                            # 检查是否有有效的 candidates 响应
                            if "candidates" in resp_json and resp_json["candidates"]:
                                return {
                                    "code": 0,
                                    "message": f"连接成功（格式: {fmt_name}）",
                                    "data": {
                                        "success": True,
                                        "model": test_model,
                                        "format": fmt_name
                                    }
                                }
                            else:
                                # 200 但无 candidates，可能是错误信息
                                error_info = resp_json.get("error", {})
                                error_msg = error_info.get("message", "响应无效")
                                last_error = f"{fmt_name}: {error_msg}"
                                last_error_message = f"API 返回错误: {error_msg}"
                                continue  # 尝试下一种格式
                        except Exception:
                            last_error = f"{fmt_name}: 响应解析失败"
                            continue
                    
                    elif response.status_code in [401, 403]:
                        # 认证错误，说明格式对了但 key 错了
                        error_type = "无效或未授权" if response.status_code == 401 else "权限不足或已被禁用"
                        return {
                            "code": 1,
                            "message": f"API Key {error_type}（格式: {fmt_name}）",
                            "data": {"success": False, "error": f"HTTP {response.status_code}", "format": fmt_name}
                        }
                    
                    # 404 或其他错误，继续尝试下一种格式
                    last_error = f"{fmt_name}: HTTP {response.status_code}"
                    
                except httpx.TimeoutException:
                    last_error = f"{fmt_name}: 连接超时"
                    continue
                except Exception as e:
                    last_error = f"{fmt_name}: {str(e)}"
                    continue
            
            # 所有格式都失败
            return {
                "code": 1,
                "message": last_error_message or f"连接失败: {last_error}",
                "data": {"success": False, "error": last_error}
            }
                
    except httpx.TimeoutException:
        return {
            "code": 1,
            "message": "连接超时，请检查网络或 Base URL",
            "data": {"success": False, "error": "Timeout"}
        }
    except Exception as e:
        logger.error(f"Failed to test Google connection: {e}")
        return {
            "code": 1,
            "message": f"连接失败: {str(e)}",
            "data": {"success": False, "error": str(e)}
        }


@router.post("/config/test-qwen")
async def admin_test_qwen_connection(
    request: TestQwenRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    测试 Qwen API 连接
    通过发送一个简单的请求验证 API Key 有效性
    """
    admin = await require_admin(auth_token)

    if not request.api_key:
        raise HTTPException(status_code=400, detail="API Key 不能为空")

    # 构建请求 URL
    base_url = request.base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    base_url = base_url.rstrip("/")

    # 测试模型
    test_model = "qwen-plus"

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {request.api_key}"
    }

    # 构建最简单的测试请求
    test_payload = {
        "model": test_model,
        "messages": [
            {"role": "user", "content": "Hi"}
        ],
        "max_tokens": 10,
        "temperature": 0.1
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            url = f"{base_url}/chat/completions"

            try:
                response = await client.post(url, headers=headers, json=test_payload)

                if response.status_code == 200:
                    try:
                        resp_json = response.json()
                        if "choices" in resp_json and resp_json["choices"]:
                            return {
                                "code": 0,
                                "message": "连接成功",
                                "data": {
                                    "success": True,
                                    "model": test_model
                                }
                            }
                        else:
                            error_msg = resp_json.get("error", {}).get("message", "响应无效")
                            return {
                                "code": 1,
                                "message": f"API 返回错误: {error_msg}",
                                "data": {"success": False, "error": error_msg}
                            }
                    except Exception:
                        return {
                            "code": 1,
                            "message": "响应解析失败",
                            "data": {"success": False, "error": "Response parse failed"}
                        }

                elif response.status_code in [401, 403]:
                    error_type = "无效或未授权" if response.status_code == 401 else "权限不足或已被禁用"
                    return {
                        "code": 1,
                        "message": f"API Key {error_type}",
                        "data": {"success": False, "error": f"HTTP {response.status_code}"}
                    }

                else:
                    try:
                        error_data = response.json()
                        error_msg = error_data.get("error", {}).get("message", f"HTTP {response.status_code}")
                    except Exception:
                        error_msg = f"HTTP {response.status_code}"

                    return {
                        "code": 1,
                        "message": f"连接失败: {error_msg}",
                        "data": {"success": False, "error": error_msg}
                    }

            except httpx.TimeoutException:
                return {
                    "code": 1,
                    "message": "连接超时，请检查网络或 Base URL",
                    "data": {"success": False, "error": "Timeout"}
                }
            except Exception as e:
                return {
                    "code": 1,
                    "message": f"连接失败: {str(e)}",
                    "data": {"success": False, "error": str(e)}
                }

    except Exception as e:
        logger.error(f"Failed to test Qwen connection: {e}")
        return {
            "code": 1,
            "message": f"连接失败: {str(e)}",
            "data": {"success": False, "error": str(e)}
        }


# ==================== 实现方算力配置 API ====================

from model.implementation_power import ImplementationPowerModel


@router.get("/implementation-powers")
async def admin_get_implementation_powers(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取所有实现方的算力配置
    返回实现方列表及其算力配置（包含数据库配置和代码默认值）
    """
    await require_admin(auth_token)

    try:
        # 获取所有实现方配置
        all_implementations = UnifiedConfigRegistry.get_all_implementations()

        # 获取数据库中的算力配置
        db_powers = ImplementationPowerModel.get_all_powers()

        # 合并数据
        result = []
        for impl_name, impl_config in all_implementations.items():
            # 查找该实现方的数据库配置
            db_config = [p for p in db_powers if p['implementation_name'] == impl_name]

            # 构建返回数据
            impl_data = {
                'name': impl_name,
                'display_name': impl_config.display_name,
                'driver_class': impl_config.driver_class,
                'default_computing_power': impl_config.default_computing_power,
                'enabled': impl_config.enabled,
                'description': impl_config.description,
                'db_config': db_config,
                'source': 'database' if db_config else 'code_default'
            }
            result.append(impl_data)

        return {
            "code": 0,
            "data": result
        }
    except Exception as e:
        logger.error(f"Failed to get implementation powers: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class SetImplementationPowerRequest(BaseModel):
    implementation_name: str
    driver_key: str  # 必填，用于复合唯一键定位记录
    computing_power: int
    duration: Optional[int] = None  # None表示固定算力，否则为特定时长的算力


@router.post("/implementation-power")
async def admin_set_implementation_power(
    request: SetImplementationPowerRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    设置实现方算力（管理员操作，立即生效，无需重启）

    Args:
        implementation_name: 实现方名称（如 gemini_duomi_v1）
        computing_power: 算力值
        duration: 时长（秒），不传表示固定算力
    """
    admin = await require_admin(auth_token)

    # 验证实现方存在
    impl_config = UnifiedConfigRegistry.get_implementation(request.implementation_name)
    if not impl_config:
        raise HTTPException(status_code=404, detail=f"实现方不存在: {request.implementation_name}")

    if request.computing_power < 0:
        raise HTTPException(status_code=400, detail="算力值不能为负数")

    try:
        ImplementationPowerModel.set_power(
            implementation_name=request.implementation_name,
            driver_key=request.driver_key,
            computing_power=request.computing_power,
            duration=request.duration,
            updated_by=admin.id
        )

        return {
            "code": 0,
            "message": f"算力配置已更新，立即生效",
            "data": {
                "implementation_name": request.implementation_name,
                "computing_power": request.computing_power,
                "duration": request.duration
            }
        }
    except Exception as e:
        logger.error(f"Failed to set implementation power: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class DeleteImplementationPowerRequest(BaseModel):
    implementation_name: str
    driver_key: str  # 必填，用于复合唯一键定位记录
    duration: Optional[int] = None


@router.delete("/implementation-power")
async def admin_delete_implementation_power(
    request: DeleteImplementationPowerRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    删除实现方算力配置（回退到代码默认值）

    Args:
        implementation_name: 实现方名称
        duration: 时长（秒），不传表示删除固定算力配置
    """
    await require_admin(auth_token)

    try:
        affected = ImplementationPowerModel.delete_power(
            implementation_name=request.implementation_name,
            driver_key=request.driver_key,
            duration=request.duration
        )

        if affected > 0:
            return {
                "code": 0,
                "message": "算力配置已删除，将使用代码默认值"
            }
        else:
            return {
                "code": 0,
                "message": "未找到对应的算力配置"
            }
    except Exception as e:
        logger.error(f"Failed to delete implementation power: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 实现方配置（启用/禁用）API ====================

class SetImplementationConfigRequest(BaseModel):
    implementation_name: str
    driver_key: str  # 必填，用于复合唯一键定位记录
    enabled: Optional[bool] = None
    sort_order: Optional[int] = None


@router.put("/implementation-config")
async def admin_set_implementation_config(
    request: SetImplementationConfigRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    设置实现方配置（启用/禁用、排序顺序等）

    管理员操作，立即生效，无需重启服务
    操作会记录审计日志

    注意：显示名称由系统自动管理，不支持手动设置。
    API聚合站点的显示名称从 api_aggregator.site_X.name 配置读取。

    Args:
        implementation_name: 实现方名称（如 gemini_duomi_v1）
        driver_key: DriverKey（必填）
        enabled: 是否启用（True/False）
        sort_order: 排序顺序（可选）
    """
    admin = await require_admin(auth_token)

    # 验证实现方存在
    impl_config = UnifiedConfigRegistry.get_implementation(request.implementation_name)
    if not impl_config:
        raise HTTPException(status_code=404, detail=f"实现方不存在: {request.implementation_name}")

    try:
        success = ImplementationPowerModel.set_config(
            implementation_name=request.implementation_name,
            driver_key=request.driver_key,
            enabled=request.enabled,
            sort_order=request.sort_order,
            updated_by=admin.id
        )

        if success:
            return {
                "code": 0,
                "message": "配置已更新，立即生效",
                "data": {
                    "implementation_name": request.implementation_name,
                    "driver_key": request.driver_key,
                    "enabled": request.enabled,
                    "sort_order": request.sort_order
                }
            }
        else:
            return {
                "code": 1,
                "message": "配置未变更（可能是相同的值）"
            }
    except Exception as e:
        logger.error(f"Failed to set implementation config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/implementation-configs")
async def admin_get_implementation_configs(
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取所有实现方配置（包含启用状态），按模型任务（DriverKey）分组返回

    返回所有实现方，包括动态注册的 API 聚合器实现方
    """
    await require_admin(auth_token)

    try:
        # 构建反向映射：实现方 -> DriverKey 列表
        impl_to_driver_keys = {}
        for driver_key, impl_names in DRIVER_IMPLEMENTATION_MAPPING.items():
            # 支持单个实现方（字符串）和多个实现方（列表）
            if isinstance(impl_names, str):
                impl_names = [impl_names]
            
            for impl_name in impl_names:
                if impl_name not in impl_to_driver_keys:
                    impl_to_driver_keys[impl_name] = []
                impl_to_driver_keys[impl_name].append(driver_key)

        # 获取所有实现方（包括动态注册的 API 聚合器实现方）
        all_implementations = UnifiedConfigRegistry.get_all_implementations()

        # 获取数据库中的配置
        db_configs = ImplementationPowerModel.get_all_configs()
        # 使用 (implementation_name, driver_key) 作为复合键
        db_config_map = {(c['implementation_name'], c.get('driver_key')): c for c in db_configs}

        # 获取所有任务配置，提取实现方支持的时长和算力配置
        impl_durations = {}
        # 追踪 (impl_name, driver_key) -> task_config.computing_power 的映射
        impl_driver_computing_power = {}
        for task_config in UnifiedConfigRegistry.get_all():
            driver_name = task_config.driver_name
            if not driver_name:
                continue

            # 兼容单数和复数形式的 implementation 属性
            impl_names = []
            if hasattr(task_config, 'implementations') and task_config.implementations:
                impl_names = task_config.implementations if isinstance(task_config.implementations, list) else [task_config.implementations]
            elif hasattr(task_config, 'implementation') and task_config.implementation:
                impl_names = [task_config.implementation] if not isinstance(task_config.implementation, list) else task_config.implementation

            for impl_name in impl_names:
                if impl_name not in impl_durations:
                    impl_durations[impl_name] = set()
                if hasattr(task_config, 'supported_durations'):
                    impl_durations[impl_name].update(task_config.supported_durations)

                # 追踪 task_config.computing_power，按 (impl_name, driver_key) 存储
                # 只存储有意义的算力值（非0、非空）
                if task_config.computing_power:
                    key = (impl_name, driver_name)
                    if key not in impl_driver_computing_power:
                        impl_driver_computing_power[key] = task_config.computing_power

        # 按 DriverKey 分组
        driver_key_groups = {}

        # 处理所有实现方（包括动态注册的 API 聚合器实现方）
        for impl_name, impl_config in all_implementations.items():
            # 只对 API 聚合器实现方进行配置检查
            display_name = impl_config.display_name
            site_name = None

            is_api_aggregator = False
            site_id = None

            if impl_config.site_number is not None:
                is_api_aggregator = True
                site_id = f"site_{impl_config.site_number}"

            if is_api_aggregator and site_id:
                # 检查API聚合器配置是否存在
                try:
                    from utils.config_checker import check_api_aggregator_config_exists
                    from config.config_util import get_dynamic_config_value

                    if not check_api_aggregator_config_exists(site_id):
                        logger.info(f"API聚合站实现方 {impl_name} 配置不存在，跳过显示")
                        continue

                    # 获取站点配置的名称
                    site_name = get_dynamic_config_value("api_aggregator", site_id, "name", default=site_id)
                    display_name = site_name

                except Exception:
                    logger.warning(f"无法导入配置检查工具，显示所有API聚合站实现方")
            else:
                # 非API聚合器实现方：检查驱动配置是否可用
                try:
                    from task.visual_drivers.driver_factory import VideoDriverFactory
                    from task.visual_drivers.base_video_driver import DriverConfigError

                    driver_class = VideoDriverFactory._registered_drivers.get(impl_name)
                    if driver_class:
                        try:
                            driver_class()  # 尝试实例化验证配置
                        except (DriverConfigError, Exception):
                            # 配置缺失或其他错误，跳过该实现方
                            continue
                except Exception:
                    pass  # 导入失败时不过滤

            # 确定该实现方属于哪些 DriverKey 组
            driver_keys = impl_to_driver_keys.get(impl_name, [])

            # 对于 API 聚合器实现方，创建特殊的分组
            if not driver_keys and impl_name.startswith('gemini_common_'):
                driver_keys = ["API_AGGREGATOR_GEMINI"]

            # 为每个 driver_key 获取对应的数据库配置
            for driver_key in driver_keys:
                # 使用复合键 (implementation_name, driver_key) 获取配置
                db_config = db_config_map.get((impl_name, driver_key), {})

                # 获取该实现方支持的时长列表
                supported_durations = sorted(list(impl_durations.get(impl_name, [])))

                # 获取该实现方的算力配置（按时长分组）
                power_configs = ImplementationPowerModel.get_all_powers_for_implementation(impl_name, driver_key)

                # 构建时长-算力映射
                duration_powers = []
                for duration in supported_durations:
                    power = power_configs.get(duration)

                    # 如果数据库没有配置，尝试从任务配置或实现方默认配置获取
                    if power is None:
                        # 优先使用任务配置中的 computing_power
                        task_computing_power = impl_driver_computing_power.get((impl_name, driver_key), impl_config.default_computing_power)
                        if isinstance(task_computing_power, dict) and duration in task_computing_power:
                            power = task_computing_power[duration]
                        elif isinstance(task_computing_power, dict) and task_computing_power:
                            # 如果是字典但没有对应时长，使用第一个值
                            power = list(task_computing_power.values())[0]
                        else:
                            power = task_computing_power

                    duration_powers.append({
                        'duration': duration,
                        'computing_power': power
                    })

                impl_data = {
                    'name': impl_name,
                    'display_name': display_name if impl_config.site_number is not None else (db_config.get('display_name') if db_config else None) or display_name,  # 聚合站点始终使用系统配置名称，其他实现方优先使用数据库值
                    'enabled': bool(db_config.get('enabled')) if db_config and db_config.get('enabled') is not None else impl_config.enabled,
                    'sort_order': db_config.get('sort_order') if db_config else impl_config.sort_order,  # 优先使用数据库排序，否则使用配置文件默认值
                    'driver_key': db_config.get('driver_key') if db_config else impl_config.driver_class,  # 使用 driver_key 字段
                    # 优先使用任务配置中的 computing_power，其次使用实现方的默认算力
                    'default_computing_power': impl_driver_computing_power.get((impl_name, driver_key), impl_config.default_computing_power),
                    'description': impl_config.description,
                    'driver_class': impl_config.driver_class,
                    'supported_durations': supported_durations,
                    'duration_powers': duration_powers,
                }

                # 调试日志：输出实现方数据
                logger.debug(f"Implementation data: {impl_name}, driver_key={driver_key}, enabled={impl_data['enabled']}, db_config={db_config}")

                # 为没有时长配置的实现方添加当前默认算力值
                if not duration_powers:
                    # 获取固定算力配置（duration = None）
                    fixed_power = power_configs.get(None)
                    if fixed_power is not None:
                        impl_data['current_default_power'] = fixed_power
                    else:
                        # 优先使用任务配置中的 computing_power，其次使用实现方的默认算力
                        task_computing_power = impl_driver_computing_power.get((impl_name, driver_key), impl_config.default_computing_power)
                        if isinstance(task_computing_power, dict) and task_computing_power:
                            impl_data['current_default_power'] = list(task_computing_power.values())[0]
                        else:
                            impl_data['current_default_power'] = task_computing_power or 0
                else:
                    # 为有时长配置的实现方添加每个时长的默认值
                    impl_data['default_duration_powers'] = {}
                    for duration in supported_durations:
                        # 优先使用任务配置中的 computing_power，其次使用实现方的默认算力
                        task_computing_power = impl_driver_computing_power.get((impl_name, driver_key), impl_config.default_computing_power)
                        if isinstance(task_computing_power, dict) and duration in task_computing_power:
                            impl_data['default_duration_powers'][duration] = task_computing_power[duration]
                        elif isinstance(task_computing_power, dict) and task_computing_power:
                            impl_data['default_duration_powers'][duration] = list(task_computing_power.values())[0]
                        else:
                            impl_data['default_duration_powers'][duration] = task_computing_power or 0

                # 将实现方添加到对应的 DriverKey 组
                if driver_key not in driver_key_groups:
                    driver_key_groups[driver_key] = []
                driver_key_groups[driver_key].append(impl_data)

        # 对每组内的实现方按 sort_order 排序
        for driver_key in driver_key_groups:
            driver_key_groups[driver_key].sort(key=lambda x: (x['sort_order'] or 0, x['name']))

        # 转换为列表格式，按 DriverKey 排序
        result = [
            {
                'driver_key': driver_key,
                'implementations': impls
            }
            for driver_key, impls in sorted(driver_key_groups.items())
        ]

        # 获取重试总开关状态
        retry_global_enabled = True
        try:
            from config.config_util import get_dynamic_config_value
            retry_global_enabled = get_dynamic_config_value("retry_settings", "global_enabled", default=False)
        except Exception:
            pass

        return {
            "code": 0,
            "data": result,
            "retry_global_enabled": retry_global_enabled
        }
    except Exception as e:
        logger.error(f"Failed to get implementation configs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateSortOrderRequest(BaseModel):
    updates: List[dict]  # [{'implementation_name': str, 'driver_key': str, 'sort_order': int}]


@router.post("/implementation-configs/sort-order")
async def admin_update_sort_orders(
    request: UpdateSortOrderRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    批量更新实现方的排序顺序

    用于拖拽排序后保存新的顺序
    """
    admin = await require_admin(auth_token)

    if not request.updates:
        raise HTTPException(status_code=400, detail="更新列表不能为空")

    try:
        success_count = 0
        for update in request.updates:
            impl_name = update.get('implementation_name')
            driver_key = update.get('driver_key')
            sort_order = update.get('sort_order')

            if impl_name is None or driver_key is None or sort_order is None:
                logger.warning(f"Invalid update parameters: {update}")
                continue

            # 使用复合键 (implementation_name, driver_key) 查询和更新配置
            existing_config = ImplementationPowerModel.get_config(impl_name, driver_key)

            ImplementationPowerModel.set_config(
                implementation_name=impl_name,
                driver_key=driver_key,
                sort_order=sort_order,
                updated_by=admin.id
            )
            success_count += 1
            logger.info(f"Updated sort order for {impl_name} (driver_key: {driver_key}) to {sort_order}")

        return {
            "code": 0,
            "message": f"成功更新 {success_count} 个实现方的排序",
            "data": {"updated_count": success_count}
        }
    except Exception as e:
        logger.error(f"Failed to update sort orders: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== 模型管理 API ====================

from model.model import ModelModel
from model.vendor_model import VendorModelModel
from model.vendor import VendorDAO
from config.constant import AdminBillingConstants, LLMVendor, LLMModel, PeakValleyBillingConstants
import json
import re
import math


def _power_yuan() -> float:
    return float(AdminBillingConstants.POWER_YUAN)


def _threshold_from_yuan_per_m(yuan_per_m: float) -> int:
    """元/百万 token → threshold（每 N token 扣 1 算力）"""
    if yuan_per_m is None or float(yuan_per_m) <= 0:
        raise HTTPException(status_code=400, detail="单价(元/百万token)必须大于 0")
    th = int(round(_power_yuan() * AdminBillingConstants.YUAN_PER_M_SCALE / float(yuan_per_m)))
    return max(1, th)


def _yuan_per_m_from_threshold(threshold: Optional[int]) -> Optional[float]:
    if not threshold or int(threshold) <= 0:
        return None
    return round(_power_yuan() * AdminBillingConstants.YUAN_PER_M_SCALE / float(threshold), 6)


def _money_snapshot(input_th, out_th, cache_th, commission_rate: float = 0.0) -> dict:
    """按阈值与抽成生成用户价/成本价（元/百万）。"""
    rate = float(commission_rate or 0)
    if rate < 0:
        rate = 0.0
    if rate > AdminBillingConstants.MAX_COMMISSION_RATE:
        rate = AdminBillingConstants.MAX_COMMISSION_RATE

    def one(th):
        cost = _yuan_per_m_from_threshold(th)
        if cost is None:
            return {'cost_yuan_per_m': None, 'user_yuan_per_m': None, 'profit_yuan_per_m': None}
        user = round(cost * (1.0 + rate), 6)
        profit = round(cost * rate, 6)
        return {
            'cost_yuan_per_m': cost,
            'user_yuan_per_m': user,
            'profit_yuan_per_m': profit,
        }

    return {
        'input': one(input_th),
        'output': one(out_th),
        'cache': one(cache_th),
        'commission_rate': rate,
    }


def _normalize_commission_rate(rate: Optional[float]) -> float:
    if rate is None:
        return 0.0
    r = float(rate)
    if r < 0 or r > AdminBillingConstants.MAX_COMMISSION_RATE:
        raise HTTPException(
            status_code=400,
            detail=f"commission_rate 必须在 0~{AdminBillingConstants.MAX_COMMISSION_RATE} 之间（0~100%）"
        )
    return r


def _normalize_time_period(period: Optional[str], *, strict: bool = False) -> str:
    """规范化计费时段。

    Args:
        period: 输入时段值（normal/peak/off_peak）
        strict: True 时非法值抛 400；False 时回退 normal
    """
    p = (period or PeakValleyBillingConstants.PERIOD_NORMAL).strip().lower()
    if p in PeakValleyBillingConstants.ALL_PERIODS:
        return p
    if strict:
        raise HTTPException(
            status_code=400,
            detail=f"time_period 必须是 {list(PeakValleyBillingConstants.ALL_PERIODS)} 之一"
        )
    return PeakValleyBillingConstants.PERIOD_NORMAL


def _resolve_thresholds_from_request(
    input_token_threshold: Optional[int],
    out_token_threshold: Optional[int],
    cache_read_threshold: Optional[int],
    input_yuan_per_m: Optional[float],
    out_yuan_per_m: Optional[float],
    cache_yuan_per_m: Optional[float],
    existing=None,
) -> tuple:
    """优先元/百万，否则用 threshold；更新时缺省回落 existing。"""
    if input_yuan_per_m is not None:
        input_th = _threshold_from_yuan_per_m(input_yuan_per_m)
    elif input_token_threshold is not None:
        input_th = int(input_token_threshold)
    elif existing is not None:
        input_th = existing.input_token_threshold
    else:
        input_th = None

    if out_yuan_per_m is not None:
        out_th = _threshold_from_yuan_per_m(out_yuan_per_m)
    elif out_token_threshold is not None:
        out_th = int(out_token_threshold)
    elif existing is not None:
        out_th = existing.output_token_threshold
    else:
        out_th = None

    if cache_yuan_per_m is not None:
        cache_th = _threshold_from_yuan_per_m(cache_yuan_per_m)
    elif cache_read_threshold is not None:
        cache_th = int(cache_read_threshold)
    elif existing is not None:
        cache_th = existing.cache_read_threshold
    else:
        cache_th = None

    return input_th, out_th, cache_th


def _enrich_tier_dict(tier: dict) -> dict:
    """为档位补充元/百万与 money 快照。"""
    rate = float(tier.get('commission_rate') or 0)
    in_th = tier.get('input_token_threshold')
    out_th = tier.get('out_token_threshold') or tier.get('output_token_threshold')
    cache_th = tier.get('cache_read_threshold')
    tier['input_yuan_per_m'] = _yuan_per_m_from_threshold(in_th)
    tier['out_yuan_per_m'] = _yuan_per_m_from_threshold(out_th)
    tier['cache_yuan_per_m'] = _yuan_per_m_from_threshold(cache_th)
    tier['commission_rate'] = rate
    tier['money'] = _money_snapshot(in_th, out_th, cache_th, rate)
    return tier


def _format_token_range_label(raw_token_threshold: Optional[int], prev_threshold: Optional[int]) -> str:
    """根据当前档上界与上一档上界生成区间文案。"""
    def _fmt(n: int) -> str:
        if n >= 1000 and n % 1000 == 0:
            return f"{n // 1000}K"
        if n >= 1000:
            return f"{n / 1000:g}K"
        return str(n)

    if raw_token_threshold is None:
        if prev_threshold is None:
            return "全量（无分段）"
        return f">{_fmt(prev_threshold)}"
    if prev_threshold is None:
        return f"0–{_fmt(raw_token_threshold)}"
    return f"{_fmt(prev_threshold)}–{_fmt(raw_token_threshold)}"


def _build_model_billing_payload(model_id: int, model_name: str) -> dict:
    """组装某模型的分段计费结构（按供应商分组）。"""
    from config.default_vendor_model_billing import (
        has_defaults_for_model,
        list_default_vendor_names_for_model,
    )

    rows = VendorModelModel.list_by_model_id(model_id)
    vendors_map: dict = {}
    for row in rows:
        vendor_id = row['vendor_id']
        if vendor_id not in vendors_map:
            vendors_map[vendor_id] = {
                'vendor_id': vendor_id,
                'vendor_name': row.get('vendor_name') or f"vendor#{vendor_id}",
                'tiers': []
            }
        tier = {
            'id': row['id'],
            'raw_token_threshold': row['raw_token_threshold'],
            'input_token_threshold': row['input_token_threshold'],
            'out_token_threshold': row['out_token_threshold'],
            'cache_read_threshold': row['cache_read_threshold'],
            'commission_rate': float(row.get('commission_rate') or 0),
            'time_period': row.get('time_period') or 'normal',
            'created_at': row['created_at'].isoformat() if row.get('created_at') else None,
        }
        _enrich_tier_dict(tier)
        vendors_map[vendor_id]['tiers'].append(tier)

    default_vendor_names = list_default_vendor_names_for_model(model_name)
    default_name_set = set(default_vendor_names)

    vendors = []
    for vendor in vendors_map.values():
        prev = None
        for tier in vendor['tiers']:
            tier['range_label'] = _format_token_range_label(tier['raw_token_threshold'], prev)
            prev = tier['raw_token_threshold']
        vendor['has_defaults'] = vendor.get('vendor_name') in default_name_set
        vendors.append(vendor)

    return {
        'model_id': model_id,
        'model_name': model_name,
        'vendors': vendors,
        'power_yuan': _power_yuan(),
        'has_defaults': has_defaults_for_model(model_name),
        'default_vendor_names': default_vendor_names,
    }


def _resolve_default_tier_thresholds(tier_def: dict) -> tuple:
    """
    将默认档位定义解析为 (input_th, out_th, cache_th, raw_th, commission_rate, time_period)。
    优先使用 *_token_threshold；否则用 *_yuan_per_m 换算。
    """
    if tier_def.get('input_token_threshold') is not None:
        in_th = int(tier_def['input_token_threshold'])
    elif tier_def.get('input_yuan_per_m') is not None:
        in_th = _threshold_from_yuan_per_m(float(tier_def['input_yuan_per_m']))
    else:
        raise HTTPException(status_code=500, detail="默认档位缺少 input 单价或阈值")

    if tier_def.get('out_token_threshold') is not None:
        out_th = int(tier_def['out_token_threshold'])
    elif tier_def.get('out_yuan_per_m') is not None:
        out_th = _threshold_from_yuan_per_m(float(tier_def['out_yuan_per_m']))
    else:
        raise HTTPException(status_code=500, detail="默认档位缺少 output 单价或阈值")

    if tier_def.get('cache_read_threshold') is not None:
        cache_th = int(tier_def['cache_read_threshold'])
    elif tier_def.get('cache_yuan_per_m') is not None:
        cache_th = _threshold_from_yuan_per_m(float(tier_def['cache_yuan_per_m']))
    else:
        raise HTTPException(status_code=500, detail="默认档位缺少 cache 单价或阈值")

    raw_th = tier_def.get('raw_token_threshold', None)
    if raw_th is not None and raw_th != '':
        raw_th = int(raw_th)
    else:
        raw_th = None

    rate = _normalize_commission_rate(tier_def.get('commission_rate', 0))
    period = _normalize_time_period(tier_def.get('time_period'))
    _validate_tier_thresholds(in_th, out_th, cache_th, raw_th)
    return in_th, out_th, cache_th, raw_th, rate, period


def _validate_tier_thresholds(
    input_token_threshold: Optional[int],
    out_token_threshold: Optional[int],
    cache_read_threshold: Optional[int],
    raw_token_threshold: Optional[int],
) -> None:
    """校验阈值与分段上界合法性。"""
    for name, value in (
        ('input_token_threshold', input_token_threshold),
        ('out_token_threshold', out_token_threshold),
        ('cache_read_threshold', cache_read_threshold),
    ):
        if value is None or int(value) <= 0:
            raise HTTPException(status_code=400, detail=f"{name} 必须为正整数（每 N 个 token 消耗 1 点算力）")
    if raw_token_threshold is not None and int(raw_token_threshold) <= 0:
        raise HTTPException(status_code=400, detail="raw_token_threshold 必须为正整数，或为空表示无上限")


def _tier_fields_snapshot(vm) -> dict:
    """从 VendorModel 实体或 dict 生成 before/after 快照。"""
    if isinstance(vm, dict):
        in_th = vm.get('input_token_threshold')
        out_th = vm.get('out_token_threshold') or vm.get('output_token_threshold')
        cache_th = vm.get('cache_read_threshold')
        raw = vm.get('raw_token_threshold')
        rate = float(vm.get('commission_rate') or 0)
        tid = vm.get('id')
        vendor_id = vm.get('vendor_id')
        period = vm.get('time_period') or PeakValleyBillingConstants.PERIOD_NORMAL
    else:
        in_th = vm.input_token_threshold
        out_th = vm.output_token_threshold
        cache_th = vm.cache_read_threshold
        raw = vm.raw_token_threshold
        rate = float(getattr(vm, 'commission_rate', 0) or 0)
        tid = vm.id
        vendor_id = vm.vendor_id
        period = getattr(vm, 'time_period', None) or PeakValleyBillingConstants.PERIOD_NORMAL
    snap = {
        'id': tid,
        'vendor_id': vendor_id,
        'raw_token_threshold': raw,
        'input_token_threshold': in_th,
        'out_token_threshold': out_th,
        'cache_read_threshold': cache_th,
        'commission_rate': rate,
        'time_period': period,
        'input_yuan_per_m': _yuan_per_m_from_threshold(in_th),
        'out_yuan_per_m': _yuan_per_m_from_threshold(out_th),
        'cache_yuan_per_m': _yuan_per_m_from_threshold(cache_th),
        'money': _money_snapshot(in_th, out_th, cache_th, rate),
    }
    return snap


def _resolve_default_billing_ai_llm() -> tuple:
    """解析默认 AI 改档模型：deepseek + deepseek-v4-pro → (vendor_id, model_id, model_name)"""
    from model.database import execute_query
    row = execute_query(
        """SELECT v.id AS vendor_id, m.id AS model_id, m.model_name
           FROM vendor v
           JOIN vendor_model vm ON vm.vendor_id = v.id
           JOIN model m ON m.id = vm.model_id
           WHERE v.vendor_name = %s AND m.model_name = %s
           LIMIT 1""",
        (AdminBillingConstants.AI_DEFAULT_VENDOR, AdminBillingConstants.AI_DEFAULT_MODEL),
        fetch_one=True,
    )
    if not row:
        # 回退：只按 model_name 找
        mrow = execute_query(
            "SELECT id, model_name FROM model WHERE model_name = %s LIMIT 1",
            (AdminBillingConstants.AI_DEFAULT_MODEL,),
            fetch_one=True,
        )
        vrow = execute_query(
            "SELECT id FROM vendor WHERE vendor_name = %s LIMIT 1",
            (AdminBillingConstants.AI_DEFAULT_VENDOR,),
            fetch_one=True,
        )
        if not mrow or not vrow:
            return None, None, AdminBillingConstants.AI_DEFAULT_MODEL
        return vrow['id'], mrow['id'], mrow['model_name']
    return row['vendor_id'], row['model_id'], row['model_name']


def _extract_json_object(text: str) -> dict:
    """从 LLM 响应中提取 JSON 对象。"""
    if not text:
        raise ValueError("空响应")
    cleaned = text.strip()
    # 去掉 markdown 代码块
    fence = re.search(r'```(?:json)?\s*([\s\S]*?)```', cleaned)
    if fence:
        cleaned = fence.group(1).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        start = cleaned.find('{')
        end = cleaned.rfind('}')
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


def _build_billing_ai_system_prompt(
    model_id: int,
    model_name: str,
    current_json: str,
) -> str:
    """构造 AI 改档 system prompt：单位换算由模型完成，无法确定时必须拒绝。"""
    return "\n".join([
        "你是计费配置助手。根据用户自然语言指令，输出对 vendor_model 档位的变更方案。",
        "",
        "【计价单位】系统内部只认：元/百万 token（yuan per 1,000,000 tokens）。",
        "1 点算力 = 0.04 元。",
        "threshold = round(0.04 * 1e6 / 成本单价)；commission_rate 为 0~1；",
        "用户价 = 成本价 * (1+commission_rate)。不要把抽成折进成本单价。",
        "",
        "【单位换算·必须算对，禁止编造】",
        "- 元/千 tokens → 元/百万 tokens = 原价 × 1000",
        "  例：0.0010 元/千tokens → 1.0 元/百万token",
        "  例：0.0020 元/千tokens → 2.0 元/百万token",
        "  例：0.00020 元/千tokens → 0.2 元/百万token",
        "- 元/百万 tokens → 原样使用",
        "- 「存储 / 元/千tokens/小时」与调用 token 计费无关，必须忽略，不要写入 cache",
        "- 「命中/缓存命中」才是 cache_yuan_per_m",
        "- 若同时出现两行「基础模型」价：第 1 行=输入，第 2 行=输出",
        "",
        "【峰谷计费 time_period】",
        "- 每个档位可选计费时段：normal=通用(不分峰谷,默认) / peak=高峰 / off_peak=空闲。",
        "- 高峰时段为北京时间 9:00-12:00、14:00-18:00，其余为空闲。同一(供应商,模型,区间)可分别配置 peak 与 off_peak 两档。",
        "- 字段含义：input_yuan_per_m=输入(缓存未命中)、cache_yuan_per_m=输入(缓存命中)、out_yuan_per_m=输出。",
        "- 若用户给出「高峰/空闲(或 peak/off_peak)」两组价格，应生成 time_period 分别为 peak 与 off_peak 的【两个】create；",
        "  create 时 time_period 必填；同一区间下不同时段视为不同档位，不会冲突。",
        "- 若用户只给一组价格且未提时段，time_period 用 normal。",
        "- update 改价格但未提时段时，after 可不写 time_period（保留原时段，不要擅自改成 normal）。",
        "- delete 峰谷档位时正常按 tier_id 删除即可。",
        "",
        "【无法确定时禁止瞎填——错误答案比不回答更糟】",
        "若单位不清、数字对不上、目标档位/供应商无法确定、或你无法可靠完成换算，",
        "不要输出任何 ops，只输出：",
        '{"ok":false,"error":"简短说明原因，以及需要用户补充的信息"}',
        "",
        "成功时只输出一个 JSON 对象，不要 Markdown。格式：",
        '{"ok":true,"summary":"...", "ops":[{"op":"create|update|delete","tier_id":null或数字,'
        '"vendor_id":数字,"after":{"raw_token_threshold":数字或null,'
        '"time_period":"normal|peak|off_peak",'
        '"input_yuan_per_m":数字,"out_yuan_per_m":数字,"cache_yuan_per_m":数字,'
        '"commission_rate":0~1}}]}',
        "delete 时 after 可为 null；update 必须带已有 tier_id；create 必须带 time_period。",
        "after 中的 *_yuan_per_m 一律是【供应商成本·元/百万token】。",
        f"目标计费模型: id={model_id} name={model_name}",
        f"当前档位 JSON:\n{current_json}",
    ])


@router.get("/models")
async def admin_get_models(auth_token: str = Header(None, alias="Authorization")):
    """
    获取所有模型列表（含 enabled 状态、计费摘要、关联供应商）
    """
    await require_admin(auth_token)

    try:
        models, summaries, vendors_map = await asyncio.gather(
            asyncio.to_thread(ModelModel.get_all, 0),
            asyncio.to_thread(VendorModelModel.get_billing_summaries),
            asyncio.to_thread(VendorModelModel.list_vendors_by_models),
        )
        data = []
        for m in models:
            item = m.to_dict()
            summary = summaries.get(m.id) or {'vendor_count': 0, 'tier_count': 0}
            item['billing_summary'] = summary
            # 该模型在 vendor_model 中关联的全部供应商（AI 负责模型下拉用）
            item['vendors'] = vendors_map.get(m.id) or []
            data.append(item)
        return {
            "code": 0,
            "data": data
        }
    except Exception as e:
        logger.error(f"Failed to get models: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class UpdateModelEnabledRequest(BaseModel):
    enabled: int


@router.put("/models/{model_id}/enabled")
async def admin_update_model_enabled(
    model_id: int = Path(...),
    request: UpdateModelEnabledRequest = ...,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    切换模型启用/禁用状态
    """
    await require_admin(auth_token)

    try:
        model = await asyncio.to_thread(ModelModel.get_by_id, model_id)
        if not model:
            raise HTTPException(status_code=404, detail="模型不存在")

        enabled_val = 1 if request.enabled else 0
        await asyncio.to_thread(ModelModel.set_enabled, model_id, enabled_val)
        logger.info(f"Model {model_id} ({model.model_name}) enabled set to {enabled_val}")

        return {
            "code": 0,
            "message": f"模型 {model.model_name} 已{'启用' if enabled_val else '禁用'}",
            "data": {"model_id": model_id, "enabled": enabled_val}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update model {model_id} enabled: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/models/{model_id}/billing")
async def admin_get_model_billing(
    model_id: int = Path(...),
    auth_token: str = Header(None, alias="Authorization")
):
    """获取指定模型的供应商分段计费档位"""
    await require_admin(auth_token)

    try:
        model = await asyncio.to_thread(ModelModel.get_by_id, model_id)
        if not model:
            raise HTTPException(status_code=404, detail="模型不存在")

        payload = await asyncio.to_thread(
            _build_model_billing_payload, model_id, model.model_name
        )
        return {"code": 0, "data": payload}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get model billing for {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/vendors")
async def admin_get_vendors(auth_token: str = Header(None, alias="Authorization")):
    """获取供应商列表（用于添加计费档位）"""
    await require_admin(auth_token)

    try:
        vendors = await asyncio.to_thread(VendorDAO.get_all)
        return {
            "code": 0,
            "data": [v.to_dict() for v in vendors]
        }
    except Exception as e:
        logger.error(f"Failed to get vendors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class VendorModelTierRequest(BaseModel):
    vendor_id: int
    model_id: int
    raw_token_threshold: Optional[int] = None
    # 优先使用元/百万；未传时使用 threshold
    input_yuan_per_m: Optional[float] = None
    out_yuan_per_m: Optional[float] = None
    cache_yuan_per_m: Optional[float] = None
    input_token_threshold: Optional[int] = None
    out_token_threshold: Optional[int] = None
    cache_read_threshold: Optional[int] = None
    commission_rate: float = 0.0
    # 计费时段：normal=不分峰谷, peak=高峰, off_peak=空闲
    time_period: str = PeakValleyBillingConstants.PERIOD_NORMAL


class UpdateVendorModelTierRequest(BaseModel):
    raw_token_threshold: Optional[int] = None
    input_yuan_per_m: Optional[float] = None
    out_yuan_per_m: Optional[float] = None
    cache_yuan_per_m: Optional[float] = None
    input_token_threshold: Optional[int] = None
    out_token_threshold: Optional[int] = None
    cache_read_threshold: Optional[int] = None
    commission_rate: Optional[float] = None
    clear_raw_token_threshold: bool = False
    time_period: Optional[str] = None


@router.post("/vendor-models")
async def admin_create_vendor_model_tier(
    request: VendorModelTierRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """新增供应商模型计费档位（优先元/百万 token 录入）"""
    await require_admin(auth_token)

    try:
        input_th, out_th, cache_th = _resolve_thresholds_from_request(
            request.input_token_threshold,
            request.out_token_threshold,
            request.cache_read_threshold,
            request.input_yuan_per_m,
            request.out_yuan_per_m,
            request.cache_yuan_per_m,
        )
        _validate_tier_thresholds(input_th, out_th, cache_th, request.raw_token_threshold)
        commission_rate = _normalize_commission_rate(request.commission_rate)
        period = _normalize_time_period(request.time_period, strict=True)

        model = await asyncio.to_thread(ModelModel.get_by_id, request.model_id)
        if not model:
            raise HTTPException(status_code=404, detail="模型不存在")

        vendor = await asyncio.to_thread(VendorDAO.get_by_id, request.vendor_id)
        if not vendor:
            raise HTTPException(status_code=404, detail="供应商不存在")

        exists = await asyncio.to_thread(
            VendorModelModel.exists_tier,
            request.vendor_id,
            request.model_id,
            request.raw_token_threshold,
            None,
            period,
        )
        if exists:
            label = "无上限" if request.raw_token_threshold is None else str(request.raw_token_threshold)
            raise HTTPException(
                status_code=400,
                detail=f"该供应商-模型已存在 raw_token_threshold={label}（时段 {period}）的档位"
            )

        new_id = await asyncio.to_thread(
            VendorModelModel.create,
            request.vendor_id,
            request.model_id,
            input_th,
            out_th,
            cache_th,
            request.raw_token_threshold,
            commission_rate,
            period,
        )
        logger.info(
            f"Created vendor_model tier id={new_id} vendor={request.vendor_id} "
            f"model={request.model_id} raw={request.raw_token_threshold} "
            f"rate={commission_rate} period={period}"
        )
        data = {
            "id": new_id,
            "input_token_threshold": input_th,
            "out_token_threshold": out_th,
            "cache_read_threshold": cache_th,
            "raw_token_threshold": request.raw_token_threshold,
            "commission_rate": commission_rate,
            "time_period": period,
            "money": _money_snapshot(input_th, out_th, cache_th, commission_rate),
        }
        return {"code": 0, "message": "计费档位已创建", "data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to create vendor model tier: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/vendor-models/{tier_id}")
async def admin_update_vendor_model_tier(
    tier_id: int = Path(...),
    request: UpdateVendorModelTierRequest = ...,
    auth_token: str = Header(None, alias="Authorization")
):
    """更新供应商模型计费档位"""
    await require_admin(auth_token)

    try:
        existing = await asyncio.to_thread(VendorModelModel.get_by_id, tier_id)
        if not existing:
            raise HTTPException(status_code=404, detail="计费档位不存在")

        input_th, out_th, cache_th = _resolve_thresholds_from_request(
            request.input_token_threshold,
            request.out_token_threshold,
            request.cache_read_threshold,
            request.input_yuan_per_m,
            request.out_yuan_per_m,
            request.cache_yuan_per_m,
            existing=existing,
        )

        if request.clear_raw_token_threshold:
            raw_th = None
        elif request.raw_token_threshold is not None:
            raw_th = request.raw_token_threshold
        else:
            raw_th = existing.raw_token_threshold

        commission_rate = (
            _normalize_commission_rate(request.commission_rate)
            if request.commission_rate is not None
            else float(existing.commission_rate or 0)
        )
        period = (
            _normalize_time_period(request.time_period, strict=True)
            if request.time_period is not None
            else (existing.time_period or PeakValleyBillingConstants.PERIOD_NORMAL)
        )

        _validate_tier_thresholds(input_th, out_th, cache_th, raw_th)

        exists = await asyncio.to_thread(
            VendorModelModel.exists_tier,
            existing.vendor_id,
            existing.model_id,
            raw_th,
            tier_id,
            period,
        )
        if exists:
            label = "无上限" if raw_th is None else str(raw_th)
            raise HTTPException(
                status_code=400,
                detail=f"该供应商-模型已存在 raw_token_threshold={label}（时段 {period}）的档位"
            )

        await asyncio.to_thread(
            VendorModelModel.update_thresholds,
            tier_id,
            input_th,
            out_th,
            cache_th,
            raw_th,
            commission_rate,
            period,
        )

        logger.info(
            f"Updated vendor_model tier id={tier_id} input={input_th} out={out_th} "
            f"cache={cache_th} raw={raw_th} rate={commission_rate} period={period}"
        )
        return {
            "code": 0,
            "message": "计费档位已更新",
            "data": {
                "id": tier_id,
                "input_token_threshold": input_th,
                "out_token_threshold": out_th,
                "cache_read_threshold": cache_th,
                "raw_token_threshold": raw_th,
                "commission_rate": commission_rate,
                "time_period": period,
                "input_yuan_per_m": _yuan_per_m_from_threshold(input_th),
                "out_yuan_per_m": _yuan_per_m_from_threshold(out_th),
                "cache_yuan_per_m": _yuan_per_m_from_threshold(cache_th),
                "money": _money_snapshot(input_th, out_th, cache_th, commission_rate),
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update vendor model tier {tier_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/vendor-models/{tier_id}")
async def admin_delete_vendor_model_tier(
    tier_id: int = Path(...),
    auth_token: str = Header(None, alias="Authorization")
):
    """删除供应商模型计费档位"""
    await require_admin(auth_token)

    try:
        existing = await asyncio.to_thread(VendorModelModel.get_by_id, tier_id)
        if not existing:
            raise HTTPException(status_code=404, detail="计费档位不存在")

        ok = await asyncio.to_thread(VendorModelModel.delete, tier_id)
        if not ok:
            raise HTTPException(status_code=500, detail="删除失败")

        logger.info(
            f"Deleted vendor_model tier id={tier_id} vendor={existing.vendor_id} "
            f"model={existing.model_id}"
        )
        return {
            "code": 0,
            "message": "计费档位已删除",
            "data": {"id": tier_id}
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete vendor model tier {tier_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/{model_id}/billing/reset-defaults")
async def admin_reset_model_billing_defaults(
    model_id: int = Path(...),
    vendor_id: Optional[int] = Query(None, description="可选，仅还原该供应商；不传则还原全部默认供应商"),
    auth_token: str = Header(None, alias="Authorization"),
):
    """
    将模型计费档位还原为代码默认配置（config/default_vendor_model_billing.py）。

    - 会删除目标供应商-模型下现有全部档位后按默认重建
    - 仅支持目录中登记过的 (vendor, model)
    - vendor_id 可选：只还原该供应商；不传则还原该模型全部默认供应商
    """
    admin = await require_admin(auth_token)

    from config.default_vendor_model_billing import (
        get_default_for_vendor_model,
        list_defaults_for_model,
    )

    try:
        model = await asyncio.to_thread(ModelModel.get_by_id, model_id)
        if not model:
            raise HTTPException(status_code=404, detail="模型不存在")

        defaults = list_defaults_for_model(model.model_name)
        if not defaults:
            raise HTTPException(
                status_code=400,
                detail=f"模型 {model.model_name} 未在代码默认档位目录中登记，无法还原。"
                       f"请手动配置，或在 config/default_vendor_model_billing.py 中补充默认值。",
            )

        if vendor_id is not None:
            vendor = await asyncio.to_thread(VendorDAO.get_by_id, int(vendor_id))
            if not vendor:
                raise HTTPException(status_code=404, detail="供应商不存在")
            one = get_default_for_vendor_model(vendor.vendor_name, model.model_name)
            if not one:
                raise HTTPException(
                    status_code=400,
                    detail=f"供应商 {vendor.vendor_name} / 模型 {model.model_name} "
                           f"无代码默认档位，无法还原",
                )
            defaults = [one]

        applied = []
        skipped = []

        def _apply_one(vendor_name: str, tiers: list):
            vendor = VendorDAO.get_by_name(vendor_name)
            if not vendor:
                return None, f"数据库中不存在供应商 {vendor_name}"
            deleted = VendorModelModel.delete_by_vendor_and_model(vendor.id, model_id)
            created = []
            for tier_def in tiers:
                in_th, out_th, cache_th, raw_th, rate, period = _resolve_default_tier_thresholds(tier_def)
                new_id = VendorModelModel.create(
                    vendor.id,
                    model_id,
                    in_th,
                    out_th,
                    cache_th,
                    raw_th,
                    rate,
                    period,
                )
                created.append({
                    'id': new_id,
                    'raw_token_threshold': raw_th,
                    'input_token_threshold': in_th,
                    'out_token_threshold': out_th,
                    'cache_read_threshold': cache_th,
                    'commission_rate': rate,
                    'time_period': period,
                    'input_yuan_per_m': _yuan_per_m_from_threshold(in_th),
                    'out_yuan_per_m': _yuan_per_m_from_threshold(out_th),
                    'cache_yuan_per_m': _yuan_per_m_from_threshold(cache_th),
                })
            return {
                'vendor_id': vendor.id,
                'vendor_name': vendor_name,
                'deleted_count': deleted,
                'created_tiers': created,
            }, None

        for item in defaults:
            result, err = await asyncio.to_thread(
                _apply_one, item['vendor_name'], item.get('tiers') or []
            )
            if err:
                skipped.append({'vendor_name': item['vendor_name'], 'reason': err})
                continue
            applied.append(result)

        if not applied:
            detail = "；".join(s['reason'] for s in skipped) if skipped else "未应用任何默认档位"
            raise HTTPException(status_code=400, detail=detail)

        billing = await asyncio.to_thread(
            _build_model_billing_payload, model_id, model.model_name
        )
        logger.info(
            f"Reset billing defaults model={model_id} name={model.model_name} "
            f"applied={len(applied)} skipped={len(skipped)} "
            f"by admin={getattr(admin, 'id', None)}"
        )
        return {
            "code": 0,
            "message": f"已还原默认档位（{len(applied)} 个供应商）",
            "data": {
                "model_id": model_id,
                "model_name": model.model_name,
                "applied": applied,
                "skipped": skipped,
                "billing": billing,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reset billing defaults for model {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class BillingAiProposeRequest(BaseModel):
    instruction: str
    vendor_id: Optional[int] = None
    llm_model_id: Optional[int] = None
    llm_vendor_id: Optional[int] = None


class BillingAiApplyOp(BaseModel):
    op: str
    tier_id: Optional[int] = None
    vendor_id: Optional[int] = None
    before: Optional[dict] = None
    after: Optional[dict] = None


class BillingAiApplyRequest(BaseModel):
    ops: List[BillingAiApplyOp]


@router.post("/models/{model_id}/billing/ai-propose")
async def admin_billing_ai_propose(
    model_id: int = Path(...),
    request: BillingAiProposeRequest = ...,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    用大模型根据自然语言生成计费档位变更提案（不写库）。
    默认 LLM：deepseek / deepseek-v4-pro。
    """
    admin = await require_admin(auth_token)

    instruction = (request.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="请输入调整说明")

    try:
        model = await asyncio.to_thread(ModelModel.get_by_id, model_id)
        if not model:
            raise HTTPException(status_code=404, detail="模型不存在")

        billing = await asyncio.to_thread(
            _build_model_billing_payload, model_id, model.model_name
        )
        if request.vendor_id is not None:
            billing['vendors'] = [
                v for v in billing['vendors'] if v['vendor_id'] == request.vendor_id
            ]

        # 解析 AI 模型（默认 deepseek + deepseek-v4-pro）
        llm_vendor_id = request.llm_vendor_id
        llm_model_id = request.llm_model_id
        llm_model_name = None
        if not llm_model_id or not llm_vendor_id:
            def_v, def_m, def_name = await asyncio.to_thread(_resolve_default_billing_ai_llm)
            llm_vendor_id = llm_vendor_id or def_v
            llm_model_id = llm_model_id or def_m
            llm_model_name = def_name
        if llm_model_id and not llm_vendor_id:
            # 仅传 model_id 时取该模型任一 vendor 关联
            def _vendor_for_model(mid):
                from model.database import execute_query
                row = execute_query(
                    "SELECT vendor_id FROM vendor_model WHERE model_id = %s LIMIT 1",
                    (mid,), fetch_one=True
                )
                return row['vendor_id'] if row else None
            llm_vendor_id = await asyncio.to_thread(_vendor_for_model, llm_model_id)
        if not llm_model_id:
            raise HTTPException(
                status_code=400,
                detail="未找到默认模型 deepseek-v4-pro，请配置 DeepSeek 或指定 llm_model_id/llm_vendor_id"
            )
        llm_model_row = await asyncio.to_thread(ModelModel.get_by_id, llm_model_id)
        if not llm_model_row:
            raise HTTPException(status_code=400, detail="指定的 LLM 模型不存在")
        llm_model_name = llm_model_row.model_name

        current_json = json.dumps(billing, ensure_ascii=False, default=str)
        system_prompt = _build_billing_ai_system_prompt(
            model_id, model.model_name, current_json
        )
        user_prompt = instruction

        def _call_llm():
            from llm.llm_client_factory import get_llm_client
            client = get_llm_client(llm_model_name, vendor_id=llm_vendor_id)
            # call_api 为同步阻塞，必须在线程中调用
            return client.call_api(
                model=llm_model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=4096,
                auth_token=None,
                vendor_id=llm_vendor_id,
                model_id=llm_model_id,
                enable_thinking=False,
            )

        try:
            response = await asyncio.wait_for(
                asyncio.to_thread(_call_llm),
                timeout=float(AdminBillingConstants.AI_TIMEOUT_SEC),
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="AI 生成超时，请重试或换模型")
        except Exception as e:
            logger.error(f"Billing AI propose LLM failed: {e}")
            raise HTTPException(
                status_code=400,
                detail=f"调用大模型失败，请确认 DeepSeek API 已配置或改选其它模型: {e}"
            )

        content = ""
        try:
            content = response.choices[0].message.content or ""
        except Exception:
            content = str(response)

        try:
            parsed = _extract_json_object(content)
        except Exception as e:
            logger.error(f"Billing AI JSON parse failed: {e}; content={content[:500]}")
            raise HTTPException(status_code=400, detail=f"AI 返回无法解析为 JSON: {e}")

        # 大模型明确表示无法处理：直接 400 反馈，绝不生成可确认的错误方案
        if parsed.get('ok') is False or (
            not parsed.get('ops') and (parsed.get('error') or parsed.get('need_clarification'))
        ):
            err = (
                parsed.get('error')
                or parsed.get('need_clarification')
                or parsed.get('summary')
                or "无法可靠完成单位换算或生成方案"
            )
            raise HTTPException(
                status_code=400,
                detail=f"AI 无法处理：{err}"
            )
        # 兼容旧格式：有 ops 但未写 ok 字段时视为成功；ok=true 但无 ops 则拒绝
        if parsed.get('ok') is True and not (parsed.get('ops') or []):
            raise HTTPException(
                status_code=400,
                detail="AI 返回 ok=true 但未包含任何变更 ops，请换种描述重试"
            )

        # 构建当前 tier 索引
        tier_index = {}
        vendor_names = {}
        for v in (await asyncio.to_thread(VendorModelModel.list_by_model_id, model_id)):
            tier_index[v['id']] = v
            vendor_names[v['vendor_id']] = v.get('vendor_name')

        raw_ops = parsed.get('ops') or []
        ops_out = []
        for raw in raw_ops:
            op = (raw.get('op') or '').lower().strip()
            if op not in ('create', 'update', 'delete'):
                continue
            vendor_id = raw.get('vendor_id')
            tier_id = raw.get('tier_id')
            after_raw = raw.get('after') or {}

            if op == 'delete':
                if not tier_id or int(tier_id) not in tier_index:
                    continue
                before = _tier_fields_snapshot(tier_index[int(tier_id)])
                ops_out.append({
                    'op': 'delete',
                    'tier_id': int(tier_id),
                    'vendor_id': before['vendor_id'],
                    'vendor_name': vendor_names.get(before['vendor_id']),
                    'before': before,
                    'after': None,
                })
                continue

            # create / update：解析 after 中的元/百万或 threshold
            if op == 'update':
                if not tier_id or int(tier_id) not in tier_index:
                    continue
                existing_row = tier_index[int(tier_id)]
                vendor_id = existing_row['vendor_id']
                before = _tier_fields_snapshot(existing_row)
            else:
                if not vendor_id:
                    continue
                before = None
                vendor_id = int(vendor_id)

            try:
                in_th, out_th, cache_th = _resolve_thresholds_from_request(
                    after_raw.get('input_token_threshold'),
                    after_raw.get('out_token_threshold') or after_raw.get('output_token_threshold'),
                    after_raw.get('cache_read_threshold'),
                    after_raw.get('input_yuan_per_m'),
                    after_raw.get('out_yuan_per_m'),
                    after_raw.get('cache_yuan_per_m'),
                    existing=None if op == 'create' else type('E', (), {
                        'input_token_threshold': before['input_token_threshold'],
                        'output_token_threshold': before['out_token_threshold'],
                        'cache_read_threshold': before['cache_read_threshold'],
                    })(),
                )
                raw_th = after_raw.get('raw_token_threshold', ... )
                if raw_th is ...:
                    raw_th = before['raw_token_threshold'] if before else None
                elif raw_th == 'null' or raw_th == '':
                    raw_th = None
                rate = _normalize_commission_rate(
                    after_raw.get('commission_rate', before['commission_rate'] if before else 0)
                )
                # 时段：update 未提则保留原时段（不擅自改 normal）；create 用 AI 给定值(默认 normal)
                if op == 'update' and after_raw.get('time_period') is None:
                    period = before['time_period']
                else:
                    period = _normalize_time_period(after_raw.get('time_period'))
                _validate_tier_thresholds(in_th, out_th, cache_th, raw_th)
            except HTTPException:
                continue

            after = {
                'raw_token_threshold': raw_th,
                'time_period': period,
                'input_token_threshold': in_th,
                'out_token_threshold': out_th,
                'cache_read_threshold': cache_th,
                'commission_rate': rate,
                'input_yuan_per_m': _yuan_per_m_from_threshold(in_th),
                'out_yuan_per_m': _yuan_per_m_from_threshold(out_th),
                'cache_yuan_per_m': _yuan_per_m_from_threshold(cache_th),
                'money': _money_snapshot(in_th, out_th, cache_th, rate),
            }
            v_name = vendor_names.get(int(vendor_id))
            if not v_name:
                v_obj = await asyncio.to_thread(VendorDAO.get_by_id, int(vendor_id))
                v_name = v_obj.vendor_name if v_obj else f"vendor#{vendor_id}"
                vendor_names[int(vendor_id)] = v_name
            ops_out.append({
                'op': op,
                'tier_id': int(tier_id) if op == 'update' else None,
                'vendor_id': int(vendor_id),
                'vendor_name': v_name,
                'before': before,
                'after': after,
            })

        if not ops_out:
            raise HTTPException(
                status_code=400,
                detail="AI 未生成有效变更。若信息不足，模型应返回无法处理；"
                       "请用「元/百万 token」或明确写出「元/千 → 换算后」的输入/输出/缓存成本后重试。"
            )

        proposal = {
            'model_id': model_id,
            'model_name': model.model_name,
            'summary': parsed.get('summary') or 'AI 生成的计费调整方案',
            'ops': ops_out,
            'llm': {
                'vendor_id': llm_vendor_id,
                'model_id': llm_model_id,
                'model_name': llm_model_name,
            },
            'power_yuan': _power_yuan(),
        }
        logger.info(
            f"Billing AI propose model={model_id} ops={len(ops_out)} "
            f"by admin={getattr(admin, 'id', None)} llm={llm_model_name}"
        )
        return {"code": 0, "data": proposal}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed billing AI propose for model {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/models/{model_id}/billing/ai-apply")
async def admin_billing_ai_apply(
    model_id: int = Path(...),
    request: BillingAiApplyRequest = ...,
    auth_token: str = Header(None, alias="Authorization")
):
    """确认并应用 AI 计费档位变更提案。"""
    await require_admin(auth_token)

    if not request.ops:
        raise HTTPException(status_code=400, detail="ops 不能为空")

    try:
        model = await asyncio.to_thread(ModelModel.get_by_id, model_id)
        if not model:
            raise HTTPException(status_code=404, detail="模型不存在")

        applied = []
        # 顺序：delete → update → create，减少 raw 冲突
        ordered = sorted(
            request.ops,
            key=lambda o: {'delete': 0, 'update': 1, 'create': 2}.get((o.op or '').lower(), 9)
        )

        for item in ordered:
            op = (item.op or '').lower()
            if op == 'delete':
                if not item.tier_id:
                    raise HTTPException(status_code=400, detail="delete 需要 tier_id")
                existing = await asyncio.to_thread(VendorModelModel.get_by_id, item.tier_id)
                if not existing or existing.model_id != model_id:
                    raise HTTPException(status_code=409, detail=f"档位 {item.tier_id} 不存在或不属于该模型")
                if item.before:
                    # 乐观锁：关键字段与 before 不一致则拒绝
                    b = item.before
                    if (
                        existing.input_token_threshold != b.get('input_token_threshold')
                        or existing.output_token_threshold != b.get('out_token_threshold')
                        or existing.cache_read_threshold != b.get('cache_read_threshold')
                        or existing.raw_token_threshold != b.get('raw_token_threshold')
                    ):
                        raise HTTPException(status_code=409, detail="档位已被修改，请重新生成方案")
                await asyncio.to_thread(VendorModelModel.delete, item.tier_id)
                applied.append({'op': 'delete', 'tier_id': item.tier_id})

            elif op == 'update':
                if not item.tier_id or not item.after:
                    raise HTTPException(status_code=400, detail="update 需要 tier_id 与 after")
                existing = await asyncio.to_thread(VendorModelModel.get_by_id, item.tier_id)
                if not existing or existing.model_id != model_id:
                    raise HTTPException(status_code=409, detail=f"档位 {item.tier_id} 不存在或不属于该模型")
                if item.before:
                    b = item.before
                    if (
                        existing.input_token_threshold != b.get('input_token_threshold')
                        or existing.output_token_threshold != b.get('out_token_threshold')
                        or existing.cache_read_threshold != b.get('cache_read_threshold')
                        or existing.raw_token_threshold != b.get('raw_token_threshold')
                    ):
                        raise HTTPException(status_code=409, detail="档位已被修改，请重新生成方案")
                a = item.after
                in_th, out_th, cache_th = _resolve_thresholds_from_request(
                    a.get('input_token_threshold'),
                    a.get('out_token_threshold'),
                    a.get('cache_read_threshold'),
                    a.get('input_yuan_per_m'),
                    a.get('out_yuan_per_m'),
                    a.get('cache_yuan_per_m'),
                    existing=existing,
                )
                raw_th = a.get('raw_token_threshold', existing.raw_token_threshold)
                rate = _normalize_commission_rate(a.get('commission_rate', existing.commission_rate))
                period = _normalize_time_period(
                    a.get('time_period') if a.get('time_period') is not None
                    else (existing.time_period or PeakValleyBillingConstants.PERIOD_NORMAL)
                )
                _validate_tier_thresholds(in_th, out_th, cache_th, raw_th)
                exists = await asyncio.to_thread(
                    VendorModelModel.exists_tier, existing.vendor_id, model_id, raw_th, item.tier_id, period
                )
                if exists:
                    raise HTTPException(status_code=400, detail="分段上界与已有档位冲突")
                await asyncio.to_thread(
                    VendorModelModel.update_thresholds,
                    item.tier_id, in_th, out_th, cache_th, raw_th, rate, period,
                )
                applied.append({'op': 'update', 'tier_id': item.tier_id})

            elif op == 'create':
                if not item.after or not item.vendor_id:
                    raise HTTPException(status_code=400, detail="create 需要 vendor_id 与 after")
                a = item.after
                in_th, out_th, cache_th = _resolve_thresholds_from_request(
                    a.get('input_token_threshold'),
                    a.get('out_token_threshold'),
                    a.get('cache_read_threshold'),
                    a.get('input_yuan_per_m'),
                    a.get('out_yuan_per_m'),
                    a.get('cache_yuan_per_m'),
                )
                raw_th = a.get('raw_token_threshold')
                rate = _normalize_commission_rate(a.get('commission_rate', 0))
                period = _normalize_time_period(a.get('time_period'))
                _validate_tier_thresholds(in_th, out_th, cache_th, raw_th)
                exists = await asyncio.to_thread(
                    VendorModelModel.exists_tier, item.vendor_id, model_id, raw_th, None, period
                )
                if exists:
                    raise HTTPException(status_code=400, detail="分段上界与已有档位冲突")
                new_id = await asyncio.to_thread(
                    VendorModelModel.create,
                    item.vendor_id, model_id, in_th, out_th, cache_th, raw_th, rate, period,
                )
                applied.append({'op': 'create', 'tier_id': new_id})
            else:
                raise HTTPException(status_code=400, detail=f"未知 op: {item.op}")

        payload = await asyncio.to_thread(
            _build_model_billing_payload, model_id, model.model_name
        )
        return {
            "code": 0,
            "message": f"已应用 {len(applied)} 项变更",
            "data": {"applied": applied, "billing": payload},
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed billing AI apply for model {model_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/constants")
async def admin_get_constants(
    auth_token: str = Header(None, alias="Authorization")
):
    """获取系统中所有常量/枚举定义，用于管理后台常量参考页面"""
    await require_admin(auth_token)

    try:
        from config.constants_registry import build_constants_response
        return {
            "code": 0,
            "data": build_constants_response()
        }
    except Exception as e:
        logger.error(f"Failed to get constants: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RetryGlobalEnabledRequest(BaseModel):
    enabled: bool


@router.put("/retry-global-enabled")
async def admin_update_retry_global_enabled(
    request: RetryGlobalEnabledRequest,
    auth_token: str = Header(None, alias="Authorization")
):
    """
    更新供应商自动切换总开关

    企业版可用，社区版返回 403
    """
    from config.strategy.edition_strategy import IS_COMMUNITY_EDITION

    await require_admin(auth_token)

    if IS_COMMUNITY_EDITION:
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用，请购买商业版本后解锁该功能")

    try:
        from config.config_util import set_dynamic_config_value
        set_dynamic_config_value(
            "retry_settings", "global_enabled",
            value=request.enabled,
            value_type="bool",
            description="供应商自动切换总开关"
        )
        logger.info(f"Retry global enabled set to {request.enabled}")

        return {
            "code": 0,
            "message": f"供应商自动切换已{'开启' if request.enabled else '关闭'}",
            "data": {"enabled": request.enabled}
        }
    except Exception as e:
        logger.error(f"Failed to update retry global enabled: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ==================== RunningHub 密钥池管理（商业版专属） ====================


def _require_enterprise_for_key_pool():
    """以企业 Provider 是否成功注册作为唯一能力判断。"""
    from task.runninghub_key_pool import is_available
    if not is_available():
        raise HTTPException(status_code=403, detail="此功能仅商业版本可用")


class RunningHubKeyRequest(BaseModel):
    """新增/更新密钥池中某个槽位的配置"""
    api_key: Optional[str] = None
    max_slots: Optional[int] = None
    label: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("/runninghub-key-pool")
async def admin_get_runninghub_key_pool(
    auth_token: str = Header(None, alias="Authorization")
):
    """获取 RunningHub 密钥池聚合视图（含配置 + 运行态 + 当前占用，api_key 脱敏）"""
    await require_admin(auth_token)
    _require_enterprise_for_key_pool()
    try:
        from task.runninghub_key_pool import get_pool_overview_async
        from config.config_util import get_dynamic_config_value
        overview = await get_pool_overview_async()
        global_api_key = await asyncio.to_thread(
            get_dynamic_config_value, 'runninghub', 'api_key', default=''
        )
        return {
            "code": 0,
            "data": {
                "pool": overview,
                "global_api_key_configured": bool(
                    global_api_key
                ),
            }
        }
    except Exception as e:
        logger.error(f"Failed to get runninghub key pool: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runninghub-key-pool/{index}/raw")
async def admin_get_runninghub_key_raw(
    index: int = Path(..., ge=1, le=20),
    auth_token: str = Header(None, alias="Authorization")
):
    """查看某密钥明文（敏感，仅管理员）"""
    await require_admin(auth_token)
    _require_enterprise_for_key_pool()
    try:
        from task.runninghub_key_pool import get_key_raw_async
        api_key = await get_key_raw_async(index)
        return {"code": 0, "data": {"index": index, "api_key": api_key}}
    except KeyError as e:
        raise HTTPException(status_code=404, detail=e.args[0])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get runninghub key raw {index}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/runninghub-key-pool/{index}")
async def admin_set_runninghub_key(
    index: int = Path(..., ge=1, le=20),
    request: RunningHubKeyRequest = None,
    auth_token: str = Header(None, alias="Authorization")
):
    """新增/更新密钥池中某个槽位的配置（仅配置项，运行态由系统维护）"""
    admin = await require_admin(auth_token)
    _require_enterprise_for_key_pool()
    try:
        from task.runninghub_key_pool import set_key_async
        updated = await set_key_async(
            index,
            api_key=request.api_key,
            max_slots=request.max_slots,
            label=request.label,
            enabled=request.enabled,
            updated_by=admin.id,
        )

        logger.info(f"Admin {admin.id} updated runninghub key pool slot {index}: {updated}")
        return {"code": 0, "message": f"密钥槽位 {index} 已更新", "data": {"updated": updated}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to set runninghub key pool slot {index}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/runninghub-key-pool/{index}")
async def admin_delete_runninghub_key(
    index: int = Path(..., ge=1, le=20),
    auth_token: str = Header(None, alias="Authorization")
):
    """删除密钥池中某个槽位（清空所有配置与运行态）"""
    await require_admin(auth_token)
    _require_enterprise_for_key_pool()
    try:
        from task.runninghub_key_pool import delete_key_async
        deleted = await delete_key_async(index)
        logger.info(f"Deleted runninghub key pool slot {index} ({deleted} fields)")
        return {"code": 0, "message": f"密钥槽位 {index} 已删除", "data": {"deleted": deleted}}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to delete runninghub key pool slot {index}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/runninghub-key-pool/{index}/reset-circuit")
async def admin_reset_runninghub_circuit(
    index: int = Path(..., ge=1, le=20),
    auth_token: str = Header(None, alias="Authorization")
):
    """手动重置某密钥的熔断状态（fail_count 清零、恢复 ENABLED）"""
    await require_admin(auth_token)
    _require_enterprise_for_key_pool()
    try:
        from task.runninghub_key_pool import reset_circuit_async
        ok = await reset_circuit_async(index)
        if not ok:
            raise HTTPException(status_code=400, detail="无法重置全局密钥(index=0)")
        return {"code": 0, "message": f"密钥槽位 {index} 熔断状态已重置"}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to reset runninghub circuit {index}: {e}")
        raise HTTPException(status_code=500, detail=str(e))
