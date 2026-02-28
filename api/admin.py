"""
管理员 API 路由
"""
from fastapi import APIRouter, HTTPException, Header, Query, Path
from pydantic import BaseModel
from typing import Optional
import logging

from model.users import UsersModel, User
from model.user_tokens import UserTokensModel
from model.computing_power import ComputingPowerModel
from model.video_workflow import VideoWorkflowModel
from model.system_config import SystemConfigModel
from model.system_config_history import SystemConfigHistoryModel
from config.config_util import get_current_env, invalidate_dynamic_cache
from config.default_configs import DEFAULT_CONFIGS, init_default_configs, get_default_config_by_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


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
        
        return {
            "code": 0,
            "data": {
                "total_users": total_users,
                "active_workflows_3d": active_workflows_3d
            }
        }
    except Exception as e:
        logger.error(f"Failed to get admin dashboard data: {e}")
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


@router.get("/config/{config_key:path}")
async def admin_get_config(
    config_key: str = Path(...),
    auth_token: str = Header(None, alias="Authorization")
):
    """
    获取单个配置详情（包含修改历史）
    """
    admin = await require_admin(auth_token)
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


class UpdateConfigRequest(BaseModel):
    value: str
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
    env = get_current_env()
    
    try:
        config = SystemConfigModel.get_by_key(env, config_key)
        if not config:
            raise HTTPException(status_code=404, detail="配置不存在")
        
        # 检查是否可编辑
        if not config.editable:
            raise HTTPException(status_code=403, detail="该配置不允许修改")
        
        old_value = config.config_value
        new_value = request.value
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
